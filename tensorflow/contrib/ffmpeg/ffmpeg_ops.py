# Copyright 2016 Google Inc. All Rights Reserved.
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
# =============================================================================

"""Public ops that allow FFmpeg encoding and decoding operations."""

import os.path

from tensorflow.contrib.ffmpeg.ops import gen_decode_audio_op_py
from tensorflow.python.framework import load_library
from tensorflow.python.framework import ops
from tensorflow.python.framework import tensor_shape
from tensorflow.python.platform import resource_loader


@ops.RegisterShape('DecodeAudio')
def _decode_audio_shape(op):
  """Computes the shape of a DecodeAudio operation.

  Args:
    op: A DecodeAudio operation.

  Returns:
    A list of output shapes. There's exactly one output, the sampled audio.
    This is a rank 2 tensor with an unknown number of samples and a
    known number of channels.
  """
  try:
    channels = op.get_attr('channel_count')
  except ValueError:
    channels = None
  return [tensor_shape.TensorShape([None, channels])]


def decode_audio(contents, file_format=None, samples_per_second=None,
                 channel_count=None):
  """Create an op that decodes the contents of an audio file.

  Args:
    contents: The binary contents of the audio file to decode. This is a
        scalar.
    file_format: A string specifying which format the contents will conform
        to. This can be mp3, ogg, or wav.
    samples_per_second: The number of samples per second that is assumed.
        In some cases, resampling will occur to generate the correct sample
        rate.
    channel_count: The number of channels that should be created from the
        audio contents. If the contents have more than this number, then
        some channels will be merged or dropped. If contents has fewer than
        this, then additional channels will be created from the existing ones.

  Returns:
    A rank 2 tensor that has time along dimension 0 and channels along
    dimension 1. Dimension 0 will be `samples_per_second * length` wide, and
    dimension 1 will be `channel_count` wide.
  """
  return gen_decode_audio_op_py.decode_audio(
      contents, file_format=file_format, samples_per_second=samples_per_second,
      channel_count=channel_count)


ops.NoGradient('DecodeAudio')


def _load_library(name, op_list=None):
  """Loads a .so file containing the specified operators.

  Args:
    name: The name of the .so file to load.
    op_list: A list of names of operators that the library should have. If None
        then the .so file's contents will not be verified.

  Raises:
    NameError if one of the required ops is missing.
  """
  filename = os.path.join(resource_loader.get_data_files_path(), name)
  library = load_library.load_op_library(filename)
  for expected_op in (op_list or []):
    for lib_op in library.OP_LIST.op:
      if lib_op.name == expected_op:
        break
    else:
      raise NameError('Could not find operator %s in dynamic library %s' %
                      (expected_op, name))


_load_library('decode_audio_op.so', ['DecodeAudio'])
