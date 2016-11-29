# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
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
"""Abstractions for the head(s) of a model.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import six

from tensorflow.contrib import losses
from tensorflow.contrib import metrics as metrics_lib
from tensorflow.contrib.learn.python.learn import metric_spec
from tensorflow.contrib.learn.python.learn.estimators import estimator
from tensorflow.contrib.learn.python.learn.estimators import metric_key
from tensorflow.contrib.learn.python.learn.estimators import model_fn
from tensorflow.contrib.learn.python.learn.estimators import prediction_key
from tensorflow.contrib.session_bundle import exporter
from tensorflow.python import summary
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import init_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import nn
from tensorflow.python.ops import variable_scope
from tensorflow.python.training import training


# TODO(zakaria): add functions that creates a head and returns ModelOpFn


def _regression_head(label_name=None,
                     weight_column_name=None,
                     label_dimension=1,
                     enable_centered_bias=False, head_name=None):
  """Creates a _Head for linear regression.

  Args:
    label_name: String, name of the key in label dict. Can be null if label
        is a tensor (single headed models).
    weight_column_name: A string defining feature column name representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    label_dimension: dimension of the label for multilabels.
    enable_centered_bias: A bool. If True, estimator will learn a centered
      bias variable for each class. Rest of the model structure learns the
      residual after centered bias.
    head_name: name of the head. If provided, predictions, summary and metrics
      keys will be prefixed by the head_name and an underscore.

  Returns:
    An instance of _Head
  """
  return _RegressionHead(loss_fn=_mean_squared_loss,
                         label_name=label_name,
                         weight_column_name=weight_column_name,
                         label_dimension=label_dimension,
                         enable_centered_bias=enable_centered_bias,
                         head_name=head_name)

# TODO(zakaria): Add logistic_regression_head


def _multi_class_head(n_classes, label_name=None, weight_column_name=None,
                      enable_centered_bias=False, head_name=None,
                      thresholds=None):
  """Creates a _Head for multi class single label classification.

  The Head uses softmax cross entropy loss.

  Args:
    n_classes: Integer, number of classes, must be >= 2
    label_name: String, name of the key in label dict. Can be null if label
        is a tensor (single headed models).
    weight_column_name: A string defining feature column name representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    enable_centered_bias: A bool. If True, estimator will learn a centered
      bias variable for each class. Rest of the model structure learns the
      residual after centered bias.
    head_name: name of the head. If provided, predictions, summary and metrics
      keys will be prefixed by the head_name and an underscore.
    thresholds: thresholds for eval metrics, defaults to [.5]

  Returns:
    An instance of _MultiClassHead.

  Raises:
    ValueError: if n_classes is < 2
  """
  if (n_classes is None) or (n_classes < 2):
    raise ValueError(
        "n_classes must be > 1 for classification: %s." % n_classes)

  if n_classes == 2:
    return _BinaryLogisticHead(label_name=label_name,
                               weight_column_name=weight_column_name,
                               enable_centered_bias=enable_centered_bias,
                               head_name=head_name,
                               thresholds=thresholds)

  return _MultiClassHead(n_classes=n_classes,
                         label_name=label_name,
                         weight_column_name=weight_column_name,
                         enable_centered_bias=enable_centered_bias,
                         head_name=head_name,
                         thresholds=thresholds)


def _binary_svm_head(label_name=None, weight_column_name=None,
                     enable_centered_bias=False, head_name=None,
                     thresholds=None,):
  """Creates a `_Head` for binary classification with SVMs.

  The head uses binary hinge loss.

  Args:
    label_name: String, name of the key in label dict. Can be null if label
      is a tensor (single headed models).
    weight_column_name: A string defining feature column name representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    enable_centered_bias: A bool. If True, estimator will learn a centered
      bias variable for each class. Rest of the model structure learns the
      residual after centered bias.
    head_name: name of the head. If provided, predictions, summary and metrics
      keys will be prefixed by the head_name and an underscore.
    thresholds: thresholds for eval metrics, defaults to [.5]

  Returns:
    An instance of `_Head`.

  """
  return _BinarySvmHead(label_name=label_name,
                        weight_column_name=weight_column_name,
                        enable_centered_bias=enable_centered_bias,
                        head_name=head_name,
                        thresholds=thresholds)


def _multi_label_head(n_classes, label_name=None, weight_column_name=None,
                      enable_centered_bias=False, head_name=None,
                      thresholds=None):
  """Creates a _Head for multi label classification.

  The Head uses softmax cross entropy loss.

  Args:
    n_classes: Integer, number of classes, must be >= 2
    label_name: String, name of the key in label dict. Can be null if label
        is a tensor (single headed models).
    weight_column_name: A string defining feature column name representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    enable_centered_bias: A bool. If True, estimator will learn a centered
      bias variable for each class. Rest of the model structure learns the
      residual after centered bias.
    head_name: name of the head. If provided, predictions, summary and metrics
      keys will be prefixed by the head_name and an underscore.
    thresholds: thresholds for eval metrics, defaults to [.5]

  Returns:
    An instance of _MultiClassHead.

  Raises:
    ValueError: if n_classes is < 2
  """
  if n_classes < 2:
    raise ValueError("n_classes must be > 1 for classification.")
  return _MultiLabelHead(n_classes=n_classes,
                         label_name=label_name,
                         weight_column_name=weight_column_name,
                         enable_centered_bias=enable_centered_bias,
                         head_name=head_name,
                         thresholds=thresholds)


# TODO(zakaria): Make the classes public once we are ready for users to subclass
#   them.
class _Head(object):
  """Interface for the head/top of a model.

  Given logits or output of a hidden layer, a Head knows how to compute
  predictions, loss, default metric and export signature.
  """
  __metaclass__ = abc.ABCMeta

  @abc.abstractproperty
  def logits_dimension(self):
    raise NotImplementedError("Calling an abstract method.")

  @abc.abstractmethod
  def head_ops(self, features, labels, mode, train_op_fn, logits=None,
               logits_input=None, scope=None):
    """Returns ops for a model_fn.

    Args:
      features: input dict.
      labels: labels dict or tensor.
      mode: estimator's ModeKeys
      train_op_fn: function that takes a scalar loss and returns an op to
          optimize with the loss.
      logits: logits to be used for the head.
      logits_input: tensor to build logits from.
      scope: Optional scope for variable_scope.

    Returns:
      `ModelFnOps`.

    Raises:
      ValueError: if mode is not recognized.
    """
    raise NotImplementedError("Calling an abstract method.")


class _RegressionHead(_Head):
  """_Head for regression."""

  def __init__(self, loss_fn, label_name, weight_column_name, label_dimension,
               enable_centered_bias, head_name):
    """Base type for all single heads.

    Args:
      loss_fn: Loss function.
      label_name: String, name of the key in label dict. Can be null if label
          is a tensor (single headed models).
      weight_column_name: A string defining feature column name representing
        weights. It is used to down weight or boost examples during training. It
        will be multiplied by the loss of the example.
      label_dimension: Integer, number of label columns.
      enable_centered_bias: A bool. If True, estimator will learn a centered
        bias variable for each class. Rest of the model structure learns the
        residual after centered bias.
      head_name: name of the head. If provided, predictions, summary and metrics
        keys will be prefixed by the head_name and an underscore.
    """
    self._loss_fn = loss_fn
    self._logits_dimension = label_dimension
    self._label_name = label_name
    self._weight_column_name = weight_column_name
    self._head_name = head_name
    self._enable_centered_bias = enable_centered_bias
    self._centered_bias_weight_collection = _head_prefixed(head_name,
                                                           "centered_bias")

  @property
  def logits_dimension(self):
    return self._logits_dimension

  def head_ops(self, features, labels, mode, train_op_fn, logits=None,
               logits_input=None, scope=None):
    """See `_Head`."""
    _check_mode_valid(mode)
    _check_logits_input_not_supported(logits, logits_input)
    if self._enable_centered_bias:
      _ = _centered_bias(
          self.logits_dimension,
          self._centered_bias_weight_collection)

    predictions = self._predictions(logits)
    if (mode == model_fn.ModeKeys.INFER) or (labels is None):
      loss = None
      train_op = None
      eval_metric_ops = None
    else:
      loss = self._training_loss(features, labels, logits)
      train_op = (None if train_op_fn is None or mode == model_fn.ModeKeys.EVAL
                  else self._train_op(loss, labels, train_op_fn))
      eval_metric_ops = self._eval_metric_ops(features, labels, predictions)

    return model_fn.ModelFnOps(
        mode=mode,
        predictions=predictions,
        loss=loss,
        train_op=train_op,
        eval_metric_ops=eval_metric_ops,
        signature_fn=self._signature_fn())

  def _training_loss(self, features, labels, logits, name=None):
    """Returns training loss tensor for this head.

    Training loss is different from the loss reported on the tensorboard as we
    should respect the example weights when computing the gradient.

      L = sum_{i} w_{i} * l_{i} / B

    where B is the number of examples in the batch, l_{i}, w_{i} are individual
    losses, and example weight.

    Args:
      features: features dict.
      labels: either a tensor for labels or in multihead case, a dict of string
        to labels tensor.
      logits: logits, a float tensor.
      name: Op name.

    Returns:
      A loss `Tensor`.
    """
    labels = _check_labels(labels, self._label_name)

    with ops.name_scope(
        name, "training_loss",
        list(six.itervalues(features)) + [labels, logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)

      loss_unweighted = self._loss_fn(logits, labels)
      loss, weighted_average_loss = _loss(
          loss_unweighted,
          _weight_tensor(features, self._weight_column_name),
          name=name_scope)
      summary.scalar(
          _head_prefixed(self._head_name, "loss"), weighted_average_loss)
      return loss

  def _train_op(self, loss, labels, train_op_fn, name=None):
    """Returns op for the training step."""
    with ops.name_scope(name, "train_op", [loss, labels]):
      train_op = train_op_fn(loss)

      if self._enable_centered_bias:
        centered_bias_step = [_centered_bias_step(
            self.logits_dimension,
            self._centered_bias_weight_collection,
            labels,
            self._loss_fn)]
        train_op = control_flow_ops.group(train_op, *centered_bias_step)

      return train_op

  def _eval_metric_ops(self, features, labels, predictions, name=None):
    """Returns a dict of metric ops keyed by name."""
    labels = _check_labels(labels, self._label_name)
    with ops.name_scope(
        name, "eval_metric_ops",
        values=(list(six.itervalues(features)) + [labels] +
                list(six.itervalues(predictions)))):
      return estimator._make_metrics_ops(  # pylint: disable=protected-access
          self._default_metrics(), features, labels, predictions)

  def _predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Tensor` before applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Tensor` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "predictions", [logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)
      return self._logits_to_predictions(logits, name=name_scope)

  def _logits_to_predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Tensor` after applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Tensor` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "logits_to_predictions", [logits]):
      predictions = {}
      if self.logits_dimension == 1:
        predictions[prediction_key.PredictionKey.SCORES] = array_ops.squeeze(
            logits, squeeze_dims=[1], name=prediction_key.PredictionKey.SCORES)
      else:
        predictions[prediction_key.PredictionKey.SCORES] = logits
      return predictions

  def _signature_fn(self):
    """Returns the signature_fn to be used in exporting."""
    def _regression_signature_fn(examples, unused_features, predictions):
      if isinstance(predictions, dict):
        score = predictions[prediction_key.PredictionKey.SCORES]
      else:
        score = predictions

      default_signature = exporter.regression_signature(
          input_tensor=examples, output_tensor=score)
      # TODO(zakaria): add validation
      return default_signature, {}
    return _regression_signature_fn

  def _default_metrics(self):
    """Returns a dict of `MetricSpec` keyed by `MetricKey`."""
    return {_head_prefixed(self._head_name, metric_key.MetricKey.LOSS):
            _weighted_average_loss_metric_spec(
                self._loss_fn,
                prediction_key.PredictionKey.SCORES,
                self._label_name,
                self._weight_column_name)}


def _log_loss_with_two_classes(logits, labels, name=None):
  with ops.name_scope(name, "log_loss_with_two_classes",
                      [logits, labels]) as name_scope:
    # sigmoid_cross_entropy_with_logits requires [batch_size, 1] labels.
    if len(labels.get_shape()) == 1:
      labels = array_ops.expand_dims(labels, dim=[1])
    return nn.sigmoid_cross_entropy_with_logits(
        logits, math_ops.to_float(labels), name=name_scope)


class _BinaryLogisticHead(_Head):
  """_Head for binary logistic classifciation."""

  def __init__(self, label_name, weight_column_name, enable_centered_bias,
               head_name, loss_fn=_log_loss_with_two_classes, thresholds=None):
    """Base type for all single heads.

    Args:
      label_name: String, name of the key in label dict. Can be null if label
          is a tensor (single headed models).
      weight_column_name: A string defining feature column name representing
        weights. It is used to down weight or boost examples during training. It
        will be multiplied by the loss of the example.
      enable_centered_bias: A bool. If True, estimator will learn a centered
        bias variable for each class. Rest of the model structure learns the
        residual after centered bias.
      head_name: name of the head. If provided, predictions, summary and metrics
        keys will be prefixed by the head_name and an underscore.
      loss_fn: Loss function.
      thresholds: thresholds for eval.

    Raises:
      ValueError: if n_classes is invalid.
    """
    self._thresholds = thresholds if thresholds else [.5]
    self._label_name = label_name
    self._weight_column_name = weight_column_name
    self._head_name = head_name
    self._loss_fn = loss_fn
    self._enable_centered_bias = enable_centered_bias
    self._centered_bias_weight_collection = _head_prefixed(head_name,
                                                           "centered_bias")

  @property
  def logits_dimension(self):
    return 1

  def head_ops(self, features, labels, mode, train_op_fn, logits=None,
               logits_input=None, scope=None):
    """See `_Head`."""
    _check_mode_valid(mode)
    _check_logits_input_not_supported(logits, logits_input)
    if self._enable_centered_bias:
      _ = _centered_bias(
          self.logits_dimension,
          self._centered_bias_weight_collection)

    predictions = self._predictions(logits)
    if (mode == model_fn.ModeKeys.INFER) or (labels is None):
      loss = None
      train_op = None
      eval_metric_ops = None
    else:
      loss = self._training_loss(features, labels, logits)
      train_op = (None if train_op_fn is None
                  else self._train_op(loss, labels, train_op_fn))
      eval_metric_ops = self._eval_metric_ops(features, labels, predictions)

    return model_fn.ModelFnOps(
        mode=mode,
        predictions=predictions,
        loss=loss,
        train_op=train_op,
        eval_metric_ops=eval_metric_ops,
        signature_fn=self._signature_fn())

  def _training_loss(self, features, labels, logits=None, name=None):
    """Returns training loss tensor for this head.

    Training loss is different from the loss reported on the tensorboard as we
    should respect the example weights when computing the gradient.

      L = sum_{i} w_{i} * l_{i} / B

    where B is the number of examples in the batch, l_{i}, w_{i} are individual
    losses, and example weight.

    Args:
      features: features dict.
      labels: either a tensor for labels or in multihead case, a dict of string
        to labels tensor.
      logits: logits, a float tensor.
      name: Op name.

    Returns:
      A loss `Output`.
    """
    labels = _check_labels(labels, self._label_name)

    with ops.name_scope(
        name, "training_loss",
        list(six.itervalues(features)) + [labels, logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)

      loss_unweighted = self._loss_fn(logits, labels)
      loss, weighted_average_loss = _loss(
          loss_unweighted,
          _weight_tensor(features, self._weight_column_name),
          name=name_scope)
      summary.scalar(
          _head_prefixed(self._head_name, "loss"), weighted_average_loss)
      return loss

  def _train_op(self, loss, labels, train_op_fn, name=None):
    """Returns op for the training step."""
    with ops.name_scope(name, "train_op", [loss, labels]):
      train_op = train_op_fn(loss)

      if self._enable_centered_bias:
        centered_bias_step = [_centered_bias_step(
            self.logits_dimension,
            self._centered_bias_weight_collection,
            labels,
            self._loss_fn)]
        train_op = control_flow_ops.group(train_op, *centered_bias_step)

      return train_op

  def _eval_metric_ops(self, features, labels, predictions, name=None):
    """Returns a dict of metric ops keyed by name."""
    labels = _check_labels(labels, self._label_name)
    with ops.name_scope(
        name, "eval_metric_ops",
        values=(list(six.itervalues(features)) + [labels] +
                list(six.itervalues(predictions)))):
      return estimator._make_metrics_ops(  # pylint: disable=protected-access
          self._default_metrics(), features, labels, predictions)

  def _predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Output` before applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Output` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "predictions", [logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)
      return self._logits_to_predictions(logits, name=name_scope)

  def _logits_to_predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Output` after applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Output` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "logits_to_predictions", [logits]):
      predictions = {prediction_key.PredictionKey.LOGITS: logits}
      predictions[prediction_key.PredictionKey.LOGISTIC] = math_ops.sigmoid(
          logits, name=prediction_key.PredictionKey.LOGISTIC)
      logits = array_ops.concat(1, [array_ops.zeros_like(logits), logits])
      predictions[prediction_key.PredictionKey.PROBABILITIES] = nn.softmax(
          logits, name=prediction_key.PredictionKey.PROBABILITIES)
      predictions[prediction_key.PredictionKey.CLASSES] = math_ops.argmax(
          logits, 1, name=prediction_key.PredictionKey.CLASSES)
      return predictions

  def _signature_fn(self):
    """Returns the signature_fn to be used in exporting."""
    def _classification_signature_fn(examples, unused_features, predictions):
      """Servo signature function."""
      if isinstance(predictions, dict):
        default_signature = exporter.classification_signature(
            input_tensor=examples,
            classes_tensor=predictions[prediction_key.PredictionKey.CLASSES],
            scores_tensor=predictions[
                prediction_key.PredictionKey.PROBABILITIES])
      else:
        default_signature = exporter.classification_signature(
            input_tensor=examples,
            scores_tensor=predictions)

      # TODO(zakaria): add validation
      return default_signature, {}
    return _classification_signature_fn

  def _default_metrics(self):
    """Returns a dict of `MetricSpec` objects keyed by name."""
    metrics = {_head_prefixed(self._head_name, metric_key.MetricKey.LOSS):
               _weighted_average_loss_metric_spec(
                   self._loss_fn,
                   prediction_key.PredictionKey.LOGITS,
                   self._label_name,
                   self._weight_column_name)}

    # TODO(b/29366811): This currently results in both an "accuracy" and an
    # "accuracy/threshold_0.500000_mean" metric for binary classification.
    metrics[_head_prefixed(self._head_name, metric_key.MetricKey.ACCURACY)] = (
        metric_spec.MetricSpec(metrics_lib.streaming_accuracy,
                               prediction_key.PredictionKey.CLASSES,
                               self._label_name,
                               self._weight_column_name))
    def _add_binary_metric(key, metric_fn):
      metrics[_head_prefixed(self._head_name, key)] = (
          metric_spec.MetricSpec(metric_fn,
                                 prediction_key.PredictionKey.LOGISTIC,
                                 self._label_name,
                                 self._weight_column_name))
    _add_binary_metric(
        metric_key.MetricKey.PREDICTION_MEAN, _predictions_streaming_mean)
    _add_binary_metric(
        metric_key.MetricKey.LABEL_MEAN, _labels_streaming_mean)

    # Also include the streaming mean of the label as an accuracy baseline, as
    # a reminder to users.
    _add_binary_metric(
        metric_key.MetricKey.ACCURACY_BASELINE, _labels_streaming_mean)

    _add_binary_metric(metric_key.MetricKey.AUC, _streaming_auc)

    for threshold in self._thresholds:
      _add_binary_metric(metric_key.MetricKey.ACCURACY_MEAN % threshold,
                         _accuracy_at_threshold(threshold))
      # Precision for positive examples.
      _add_binary_metric(metric_key.MetricKey.PRECISION_MEAN % threshold,
                         _streaming_at_threshold(
                             metrics_lib.streaming_precision_at_thresholds,
                             threshold),)
      # Recall for positive examples.
      _add_binary_metric(metric_key.MetricKey.RECALL_MEAN % threshold,
                         _streaming_at_threshold(
                             metrics_lib.streaming_recall_at_thresholds,
                             threshold))
    return metrics


def _softmax_cross_entropy_loss(logits, labels, name=None):
  with ops.name_scope(name, "softmax_cross_entropy_loss",
                      [logits, labels]) as name_scope:
    # Check that we got integer for classification.
    if not labels.dtype.is_integer:
      raise ValueError("Labels dtype should be integer "
                       "Instead got %s." % labels.dtype)
    # sparse_softmax_cross_entropy_with_logits requires [batch_size] labels.
    if len(labels.get_shape()) == 2:
      labels = array_ops.squeeze(labels, squeeze_dims=[1])
    return nn.sparse_softmax_cross_entropy_with_logits(
        logits, labels, name=name_scope)


class _MultiClassHead(_Head):
  """_Head for classification."""

  def __init__(self, n_classes, label_name,
               weight_column_name, enable_centered_bias, head_name,
               loss_fn=_softmax_cross_entropy_loss, thresholds=None):
    """Base type for all single heads.

    Args:
      n_classes: Number of classes, must be greater than 2 (for 2 classes, use
          `_BinaryLogisticHead`).
      label_name: String, name of the key in label dict. Can be null if label
          is a tensor (single headed models).
      weight_column_name: A string defining feature column name representing
        weights. It is used to down weight or boost examples during training. It
        will be multiplied by the loss of the example.
      enable_centered_bias: A bool. If True, estimator will learn a centered
        bias variable for each class. Rest of the model structure learns the
        residual after centered bias.
      head_name: name of the head. If provided, predictions, summary and metrics
        keys will be prefixed by the head_name and an underscore.
      loss_fn: Loss function.
      thresholds: thresholds for eval.

    Raises:
      ValueError: if n_classes is invalid.
    """
    if (n_classes is None) or (n_classes <= 2):
      raise ValueError("n_classes must be > 2: %s." % n_classes)
    self._thresholds = thresholds if thresholds else [.5]

    self._logits_dimension = n_classes
    self._label_name = label_name
    self._weight_column_name = weight_column_name
    self._head_name = head_name
    self._loss_fn = loss_fn
    self._enable_centered_bias = enable_centered_bias
    self._centered_bias_weight_collection = _head_prefixed(head_name,
                                                           "centered_bias")

  @property
  def logits_dimension(self):
    return self._logits_dimension

  def head_ops(self, features, labels, mode, train_op_fn, logits=None,
               logits_input=None, scope=None):
    """See `_Head`."""
    _check_mode_valid(mode)
    _check_logits_input_not_supported(logits, logits_input)
    if self._enable_centered_bias:
      _ = _centered_bias(
          self.logits_dimension,
          self._centered_bias_weight_collection)

    predictions = self._predictions(logits)
    if (mode == model_fn.ModeKeys.INFER) or (labels is None):
      loss = None
      train_op = None
      eval_metric_ops = None
    else:
      loss = self._training_loss(features, labels, logits)
      train_op = (None if train_op_fn is None or mode == model_fn.ModeKeys.EVAL
                  else self._train_op(loss, labels, train_op_fn))
      eval_metric_ops = self._eval_metric_ops(features, labels, predictions)

    return model_fn.ModelFnOps(
        mode=mode,
        predictions=predictions,
        loss=loss,
        train_op=train_op,
        eval_metric_ops=eval_metric_ops,
        signature_fn=self._signature_fn())

  def _training_loss(self, features, labels, logits=None, name=None):
    """Returns training loss tensor for this head.

    Training loss is different from the loss reported on the tensorboard as we
    should respect the example weights when computing the gradient.

      L = sum_{i} w_{i} * l_{i} / B

    where B is the number of examples in the batch, l_{i}, w_{i} are individual
    losses, and example weight.

    Args:
      features: features dict.
      labels: either a tensor for labels or in multihead case, a dict of string
        to labels tensor.
      logits: logits, a float tensor.
      name: Op name.

    Returns:
      A loss `Tensor`.
    """
    labels = _check_labels(labels, self._label_name)

    with ops.name_scope(
        name, "training_loss",
        list(six.itervalues(features)) + [labels, logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)

      loss_unweighted = self._loss_fn(logits, labels)
      loss, weighted_average_loss = _loss(
          loss_unweighted,
          _weight_tensor(features, self._weight_column_name),
          name=name_scope)
      summary.scalar(
          _head_prefixed(self._head_name, "loss"), weighted_average_loss)
      return loss

  def _train_op(self, loss, labels, train_op_fn, name=None):
    """Returns op for the training step."""
    with ops.name_scope(name, "train_op", [loss, labels]):
      train_op = train_op_fn(loss)

      if self._enable_centered_bias:
        centered_bias_step = [_centered_bias_step(
            self.logits_dimension,
            self._centered_bias_weight_collection,
            labels,
            self._loss_fn)]
        train_op = control_flow_ops.group(train_op, *centered_bias_step)

      return train_op

  def _eval_metric_ops(self, features, labels, predictions, name=None):
    """Returns a dict of metric ops keyed by name."""
    labels = _check_labels(labels, self._label_name)
    with ops.name_scope(
        name, "eval_metric_ops",
        values=(list(six.itervalues(features)) + [labels] +
                list(six.itervalues(predictions)))):
      return estimator._make_metrics_ops(  # pylint: disable=protected-access
          self._default_metrics(), features, labels, predictions)

  def _predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Tensor` before applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Tensor` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "predictions", [logits]) as name_scope:
      if self._enable_centered_bias:
        centered_bias = ops.get_collection(
            self._centered_bias_weight_collection)[0]
        logits = nn.bias_add(logits, centered_bias)
      return self._logits_to_predictions(logits, name=name_scope)

  def _logits_to_predictions(self, logits, name=None):
    """Returns a dict of predictions.

    Args:
      logits: logits `Tensor` after applying possible centered bias.
      name: Op name.

    Returns:
      Dict of prediction `Tensor` keyed by `PredictionKey`.
    """
    with ops.name_scope(name, "logits_to_predictions", [logits]):
      predictions = {prediction_key.PredictionKey.LOGITS: logits}
      predictions[prediction_key.PredictionKey.PROBABILITIES] = nn.softmax(
          logits, name=prediction_key.PredictionKey.PROBABILITIES)
      predictions[prediction_key.PredictionKey.CLASSES] = math_ops.argmax(
          logits, 1, name=prediction_key.PredictionKey.CLASSES)

      return predictions

  def _signature_fn(self):
    """Returns the signature_fn to be used in exporting."""
    def _classification_signature_fn(examples, unused_features, predictions):
      """Servo signature function."""
      if isinstance(predictions, dict):
        default_signature = exporter.classification_signature(
            input_tensor=examples,
            classes_tensor=predictions[prediction_key.PredictionKey.CLASSES],
            scores_tensor=predictions[
                prediction_key.PredictionKey.PROBABILITIES])
      else:
        default_signature = exporter.classification_signature(
            input_tensor=examples,
            scores_tensor=predictions)

      # TODO(zakaria): add validation
      return default_signature, {}
    return _classification_signature_fn

  def _default_metrics(self):
    """Returns a dict of `MetricSpec` objects keyed by name."""
    metrics = {_head_prefixed(self._head_name, metric_key.MetricKey.LOSS):
               _weighted_average_loss_metric_spec(
                   self._loss_fn,
                   prediction_key.PredictionKey.LOGITS,
                   self._label_name,
                   self._weight_column_name)}

    # TODO(b/29366811): This currently results in both an "accuracy" and an
    # "accuracy/threshold_0.500000_mean" metric for binary classification.
    metrics[_head_prefixed(self._head_name, metric_key.MetricKey.ACCURACY)] = (
        metric_spec.MetricSpec(metrics_lib.streaming_accuracy,
                               prediction_key.PredictionKey.CLASSES,
                               self._label_name,
                               self._weight_column_name))

    # TODO(b/32953199): Add multiclass metrics.

    return metrics


def _check_labels(labels, label_name):
  labels = labels[label_name] if isinstance(labels, dict) else labels
  if isinstance(labels, sparse_tensor.SparseTensor):
    raise ValueError("SparseTensor is not supported as labels.")
  return labels


class _BinarySvmHead(_BinaryLogisticHead):
  """_Head for binary classification using SVMs."""

  def __init__(self, label_name, weight_column_name, enable_centered_bias,
               head_name, thresholds):
    def _loss_fn(logits, labels, name=None):
      with ops.name_scope(name, "hinge_loss", [logits, labels]) as name_scope:
        check_shape_op = control_flow_ops.Assert(
            math_ops.less_equal(array_ops.rank(labels), 2),
            ["labels shape should be either [batch_size, 1] or [batch_size]"])
        with ops.control_dependencies([check_shape_op]):
          labels = array_ops.reshape(
              labels, shape=[array_ops.shape(labels)[0], 1])
        return losses.hinge_loss(logits, labels, scope=name_scope)

    super(_BinarySvmHead, self).__init__(
        loss_fn=_loss_fn,
        label_name=label_name,
        weight_column_name=weight_column_name,
        enable_centered_bias=enable_centered_bias,
        head_name=head_name,
        thresholds=thresholds)

  def _logits_to_predictions(self, logits, name=None):
    """See `_MultiClassHead`."""
    with ops.name_scope(name, "logits_to_predictions", [logits]):
      predictions = {}
      predictions[prediction_key.PredictionKey.LOGITS] = logits
      logits = array_ops.concat(1, [array_ops.zeros_like(logits), logits])
      predictions[prediction_key.PredictionKey.CLASSES] = math_ops.argmax(
          logits, 1, name=prediction_key.PredictionKey.CLASSES)

      return predictions

  def _default_metrics(self):
    """See `_MultiClassHead`."""
    metrics = {_head_prefixed(self._head_name, metric_key.MetricKey.LOSS):
               _weighted_average_loss_metric_spec(
                   self._loss_fn,
                   prediction_key.PredictionKey.LOGITS,
                   self._label_name,
                   self._weight_column_name)}
    metrics[_head_prefixed(self._head_name, metric_key.MetricKey.ACCURACY)] = (
        metric_spec.MetricSpec(metrics_lib.streaming_accuracy,
                               prediction_key.PredictionKey.CLASSES,
                               self._label_name,
                               self._weight_column_name))
    # TODO(sibyl-vie3Poto): add more metrics relevant for svms.
    return metrics


class _MultiLabelHead(_MultiClassHead):
  """_Head for multlabel classification."""

  # TODO(zakaria): add signature and metric for multilabel.
  def __init__(self, n_classes, label_name,
               weight_column_name, enable_centered_bias, head_name,
               thresholds):

    super(_MultiLabelHead, self).__init__(
        loss_fn=_sigmoid_cross_entropy_loss,
        n_classes=n_classes,
        label_name=label_name,
        weight_column_name=weight_column_name,
        enable_centered_bias=enable_centered_bias,
        head_name=head_name,
        thresholds=thresholds)

  def _logits_to_predictions(self, logits, name=None):
    """See `_MultiClassHead`."""
    with ops.name_scope(name, "logits_to_predictions", [logits]):
      predictions = {prediction_key.PredictionKey.LOGITS: logits}
      if self.logits_dimension == 1:
        predictions[prediction_key.PredictionKey.LOGISTIC] = math_ops.sigmoid(
            logits, name=prediction_key.PredictionKey.LOGISTIC)
        logits = array_ops.concat(1, [array_ops.zeros_like(logits), logits])
      predictions[prediction_key.PredictionKey.PROBABILITIES] = (
          math_ops.sigmoid(
              logits, name=prediction_key.PredictionKey.PROBABILITIES))
      predictions[prediction_key.PredictionKey.CLASSES] = math_ops.to_int64(
          math_ops.greater(logits, 0),
          name=prediction_key.PredictionKey.CLASSES)
      return predictions


def _weighted_loss(loss, weight, name=None):
  """Returns cumulative weighted loss."""
  with ops.name_scope(name, "weighted_loss", [loss, weight]) as name_scope:
    unweighted_loss = array_ops.reshape(loss, shape=(-1,))
    weighted_loss = math_ops.mul(unweighted_loss,
                                 array_ops.reshape(
                                     weight, shape=(-1,)),
                                 name=name_scope)
    return weighted_loss


def _weight_tensor(features, weight_column_name, name=None):
  if not weight_column_name:
    return None
  else:
    with ops.name_scope(name, "weight_tensor",
                        list(six.itervalues(features))) as name_scope:
      return array_ops.reshape(
          math_ops.to_float(features[weight_column_name]),
          shape=(-1,),
          name=name_scope)


def _loss(loss_unweighted, weight, name):
  """Returns a tuple of (loss, weighted_average_loss)."""
  with ops.name_scope(name, values=[loss_unweighted, weight]) as name_scope:
    if weight is None:
      loss = math_ops.reduce_mean(loss_unweighted, name=name_scope)
      return loss, loss
    else:
      loss_weighted = _weighted_loss(loss_unweighted, weight)
      weighted_average_loss = math_ops.div(
          math_ops.reduce_sum(loss_weighted),
          math_ops.to_float(math_ops.reduce_sum(weight)),
          name="weighted_average_loss")
      loss = math_ops.reduce_mean(loss_weighted, name=name_scope)
      return loss, weighted_average_loss


def _check_logits_input_not_supported(logits, logits_input):
  if logits_input is not None or logits is None:
    raise NotImplementedError("logits_input is not supported yet, "
                              "must pass logits")


def _check_mode_valid(mode):
  """Raises ValueError if the given mode is invalid."""
  if (mode != model_fn.ModeKeys.TRAIN and
      mode != model_fn.ModeKeys.INFER and
      mode != model_fn.ModeKeys.EVAL):
    raise ValueError("mode=%s unrecognized." % str(mode))


def _centered_bias(logits_dimension, weight_collection):
  """Creates and returns centered bias."""
  centered_bias = variable_scope.get_variable(
      name="centered_bias_weight",
      shape=[logits_dimension],
      initializer=init_ops.zeros_initializer,
      trainable=True,
      collections=[weight_collection, ops.GraphKeys.GLOBAL_VARIABLES])

  biases = array_ops.reshape(centered_bias, [-1])
  for cb in range(logits_dimension):
    summary.scalar("centered_bias_%d" % cb, biases[cb])
  return centered_bias


def _centered_bias_step(logits_dimension, weight_collection, labels, loss_fn,
                        name=None):
  """Creates and returns training op for centered bias."""
  with ops.name_scope(name, "centered_bias_step", [labels]) as name_scope:
    centered_bias = ops.get_collection(weight_collection)
    batch_size = array_ops.shape(labels)[0]
    logits = array_ops.reshape(
        array_ops.tile(centered_bias[0], [batch_size]),
        [batch_size, logits_dimension])
    with ops.name_scope(None, "centered_bias", (labels, logits)):
      centered_bias_loss = math_ops.reduce_mean(
          loss_fn(logits, labels), name="training_loss")
    # Learn central bias by an optimizer. 0.1 is a convervative lr for a
    # single variable.
    return training.AdagradOptimizer(0.1).minimize(
        centered_bias_loss, var_list=centered_bias, name=name_scope)


def _head_prefixed(head_name, val):
  return "%s_%s" % (head_name, val) if head_name else val


# TODO(zakaria): use contrib losses.
def _mean_squared_loss(logits, labels, name=None):
  with ops.name_scope(name, "mean_squared_loss",
                      [logits, labels]) as name_scope:
    # To prevent broadcasting inside "-".
    if len(labels.get_shape()) == 1:
      labels = array_ops.expand_dims(labels, dim=[1])
    # TODO(zakaria): make sure it does not recreate the broadcast bug.
    if len(logits.get_shape()) == 1:
      logits = array_ops.expand_dims(logits, dim=[1])
    logits.get_shape().assert_is_compatible_with(labels.get_shape())
    return math_ops.square(logits - math_ops.to_float(labels), name=name_scope)


def _sigmoid_cross_entropy_loss(logits, labels, name=None):
  with ops.name_scope(name, "sigmoid_cross_entropy_loss",
                      [logits, labels]) as name_scope:
    # sigmoid_cross_entropy_with_logits requires [batch_size, n_classes] labels.
    return nn.sigmoid_cross_entropy_with_logits(
        logits, math_ops.to_float(labels), name=name_scope)


def _float_weights_or_none(weights, name=None):
  if weights is None:
    return None
  with ops.name_scope(name, "float_weights", [weights]) as name_scope:
    return math_ops.to_float(weights, name=name_scope)


def _weighted_average_loss_metric_spec(loss_fn, pred_key,
                                       label_key, weight_key):
  def _streaming_weighted_average_loss(predictions, labels, weights=None):
    loss_unweighted = loss_fn(predictions, labels)
    if weights is not None:
      weights = math_ops.to_float(weights)
    _, weighted_average_loss = _loss(loss_unweighted,
                                     weights,
                                     name="eval_loss")
    return metrics_lib.streaming_mean(weighted_average_loss)
  return metric_spec.MetricSpec(_streaming_weighted_average_loss,
                                pred_key, label_key, weight_key)


def _labels_streaming_mean(unused_predictions, labels, weights=None):
  return metrics_lib.streaming_mean(labels, weights=weights)


def _predictions_streaming_mean(predictions, unused_labels, weights=None):
  return metrics_lib.streaming_mean(predictions, weights=weights)


def _streaming_auc(predictions, labels, weights=None):
  return metrics_lib.streaming_auc(predictions, labels,
                                   weights=_float_weights_or_none(weights))


def _accuracy_at_threshold(threshold):

  def _accuracy_metric(predictions, labels, weights=None):
    threshold_predictions = math_ops.to_float(
        math_ops.greater_equal(predictions, threshold))
    return metrics_lib.streaming_accuracy(predictions=threshold_predictions,
                                          labels=labels,
                                          weights=weights)

  return _accuracy_metric


def _streaming_at_threshold(streaming_metrics_fn, threshold):

  def _streaming_metrics(predictions, labels, weights=None):
    precision_tensor, update_op = streaming_metrics_fn(
        predictions, labels=labels, thresholds=[threshold],
        weights=_float_weights_or_none(weights))
    return array_ops.squeeze(precision_tensor), update_op

  return _streaming_metrics
