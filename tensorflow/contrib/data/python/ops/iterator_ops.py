# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Iterator ops."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from tensorflow.python.data.ops import iterator_ops
from tensorflow.python.framework import ops
from tensorflow.python.ops import gen_dataset_ops
from tensorflow.python.training import basic_session_run_hooks
from tensorflow.python.training import saver as saver_lib
from tensorflow.python.training import session_run_hook


def make_saveable_from_iterator(iterator):
  """Returns a SaveableObject for saving/restore iterator state using Saver.

  Args:
    iterator: Iterator.

  For example:

  ```python
  with tf.Graph().as_default():
    ds = tf.data.Dataset.range(10)
    iterator = ds.make_initializable_iterator()
    # Build the iterator SaveableObject.
    saveable_obj = tf.contrib.data.make_saveable_from_iterator(iterator)
    # Add the SaveableObject to the SAVEABLE_OBJECTS collection so
    # it can be automatically saved using Saver.
    tf.add_to_collection(tf.GraphKeys.SAVEABLE_OBJECTS, saveable_obj)
    saver = tf.train.Saver()

    while continue_training:
      ... Perform training ...
      if should_save_checkpoint:
        saver.save()
  ```

  Note: When restoring the iterator, the existing iterator state is completely
  discarded. This means that any changes you may have made to the Dataset
  graph will be discarded as well! This includes the new Dataset graph
  that you may have built during validation. So, while running validation,
  make sure to run the initializer for the validation input pipeline after
  restoring the checkpoint.

  Note: Not all iterators support checkpointing yet. Attempting to save the
  state of an unsupported iterator will throw an error.
  """
  return _Saveable(iterator._iterator_resource)  # pylint: disable=protected-access


class _Saveable(saver_lib.BaseSaverBuilder.SaveableObject):
  """SaveableObject for saving/restoring iterator state."""

  def __init__(self, iterator_resource):
    serialized_iterator = gen_dataset_ops.serialize_iterator(iterator_resource)
    specs = [
        saver_lib.BaseSaverBuilder.SaveSpec(serialized_iterator, "",
                                            iterator_resource.name + "-state")
    ]
    super(_Saveable, self).__init__(iterator_resource, specs,
                                    iterator_resource.name)

  def restore(self, restored_tensors, unused_restored_shapes):
    with ops.colocate_with(self.op):
      return gen_dataset_ops.deserialize_iterator(self.op, restored_tensors[0])


class CheckpointInputPipelineHook(session_run_hook.SessionRunHook):
  """Checkpoints input pipeline state every N steps or seconds.

  This hook saves the state of the iterators in the `Graph` so that when
  training is resumed the input pipeline continues from where it left off.
  This could potentially avoid overfitting in certain pipelines where the
  number of training steps per eval are small compared to the dataset
  size or if the training pipeline is pre-empted.

  Differences from `CheckpointSaverHook`:
  1. Saves only the input pipelines in the "iterators" collection and not the
     global variables or other saveable objects.
  2. Does not write the `GraphDef` and `MetaGraphDef` to the summary.

  Example of checkpointing the training pipeline:

  ```python
  est = tf.estimator.Estimator(model_fn)
  while True:
    est.train(
        train_input_fn,
        hooks=[tf.contrib.data.CheckpointInputPipelineHook(est)],
        steps=train_steps_per_eval)
    # Note: We do not pass the hook here.
    metrics = est.evaluate(eval_input_fn)
    if should_stop_the_training(metrics):
      break
  ```

  This hook should be used if the input pipeline state needs to be saved
  separate from the model checkpoint. Doing so may be useful for a few reasons:
  1. The input pipeline checkpoint may be large, if there are large shuffle
     or prefetch buffers for instance, and may bloat the checkpoint size.
  2. If the input pipeline is shared between training and validation, restoring
     the checkpoint during validation may override the validation input
     pipeline.

  For saving the input pipeline checkpoint alongside the model weights use
  @{tf.contrib.data.make_saveable_from_iterator} directly to create a
  `SaveableObject` and add to the `SAVEABLE_OBJECTS` collection. Note, however,
  that you will need to be careful not to restore the training iterator during
  eval. You can do that by not adding the iterator to the SAVEABLE_OBJECTS
  collector when building the eval graph.
  """

  def __init__(self, estimator):
    """Initializes a `CheckpointInputPipelineHook`.

    Args:
      estimator: Estimator.

    Raises:
      ValueError: One of `save_steps` or `save_secs` should be set.
      ValueError: At most one of saver or scaffold should be set.
    """
    # `checkpoint_basename` is "input.ckpt" for non-distributed pipelines or
    # of the form "input_<task_type>_<task_id>.ckpt" for distributed pipelines.
    # Note: The default `checkpoint_basename` used by `CheckpointSaverHook` is
    # "model.ckpt". We intentionally choose the input pipeline checkpoint prefix
    # to be different to avoid conflicts with the model checkpoint.

    # pylint: disable=protected-access
    checkpoint_prefix = "input"
    if estimator._config.num_worker_replicas > 1:
      # Distributed setting.
      suffix = "_{}_{}".format(estimator._config.task_type,
                               estimator._config.task_id)
      checkpoint_prefix += suffix
    # pylint: enable=protected-access

    # We use a composition paradigm instead of inheriting from
    # `CheckpointSaverHook` because `Estimator` does an `isinstance` check
    # to check whether a `CheckpointSaverHook` is already present in the list
    # of hooks and if not, adds one. Inheriting from `CheckpointSaverHook`
    # would thwart this behavior. This hook checkpoints *only the iterators*
    # and not the graph variables.
    self._checkpoint_saver_hook = basic_session_run_hooks.CheckpointSaverHook(
        estimator.model_dir,
        save_secs=estimator._config.save_checkpoints_secs,  # pylint: disable=protected-access
        save_steps=estimator._config.save_checkpoints_steps,  # pylint: disable=protected-access
        checkpoint_basename=checkpoint_prefix + ".ckpt")

    # Name for the protocol buffer file that will contain the list of most
    # recent checkpoints stored as a `CheckpointState` protocol buffer.
    # This file, kept in the same directory as the checkpoint files, is
    # automatically managed by the `Saver` to keep track of recent checkpoints.
    # The default name used by the `Saver` for this file is "checkpoint". Here
    # we use the name "checkpoint_<checkpoint_prefix>" so that in case the
    # `checkpoint_dir` is the same as the model checkpoint directory, there are
    # no conflicts during restore.
    self._latest_filename = "checkpoint_" + checkpoint_prefix

  def begin(self):
    # Build a Saver that saves all iterators in the `GLOBAL_ITERATORS`
    # collection if no `Saver` or `Scaffold` is provided.
    # pylint: disable=protected-access
    if (self._checkpoint_saver_hook._saver is None and
        self._checkpoint_saver_hook._scaffold is None):
      iterators = ops.get_collection(iterator_ops.GLOBAL_ITERATORS)
      saveables = [_Saveable(i) for i in iterators]
      self._checkpoint_saver_hook._saver = _CustomSaver(saveables,
                                                        self._latest_filename)
    # pylint: enable=protected-access
    self._checkpoint_saver_hook.begin()

  def after_create_session(self, session, coord):
    # Check if there is an existing checkpoint. If so, restore from it.
    # pylint: disable=protected-access
    latest_checkpoint_path = saver_lib.latest_checkpoint(
        self._checkpoint_saver_hook._checkpoint_dir,
        latest_filename=self._latest_filename)
    if latest_checkpoint_path:
      self._checkpoint_saver_hook._get_saver().restore(session,
                                                       latest_checkpoint_path)
    else:
      # The checkpoint saved here is the state at step "global_step".
      # Note: We do not save the GraphDef or MetaGraphDef here.
      global_step = session.run(self._checkpoint_saver_hook._global_step_tensor)
      self._checkpoint_saver_hook._save(session, global_step)
      self._checkpoint_saver_hook._timer.update_last_triggered_step(global_step)
    # pylint: enable=protected-access

  def before_run(self, run_context):
    return self._checkpoint_saver_hook.before_run(run_context)

  def after_run(self, run_context, run_values):
    self._checkpoint_saver_hook.after_run(run_context, run_values)

  def end(self, session):
    self._checkpoint_saver_hook.end(session)


class _CustomSaver(saver_lib.Saver):
  """`Saver` with a different default `latest_filename`.

  This is used in the `CheckpointInputPipelineHook` to avoid conflicts with
  the model ckpt saved by the `CheckpointSaverHook`.
  """

  def __init__(self, var_list, latest_filename):
    super(_CustomSaver, self).__init__(var_list)
    self._latest_filename = latest_filename

  def save(self,
           sess,
           save_path,
           global_step=None,
           latest_filename=None,
           meta_graph_suffix="meta",
           write_meta_graph=True,
           write_state=True,
           strip_default_attrs=False):
    return super(_CustomSaver, self).save(
        sess, save_path, global_step, latest_filename or self._latest_filename,
        meta_graph_suffix, write_meta_graph, write_state, strip_default_attrs)
