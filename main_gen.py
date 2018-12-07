# -*- coding: utf-8 -*-
"""pointer_gen_main.ipynb

Automatically generated by Colaboratory.

"""

import numpy as np
import random
import tensorflow as tf
import tensorflow.nn as nn
import os
import glob

from data_preprocess import Vocab
from data_preprocess import Batcher
from data_preprocess import output_to_words

from model import SummarizationModel

from train_test_eval import get_config
from train_test_eval import run_training
from train_test_eval import restore_model
from train_test_eval import total_num_params

hpm={"hidden_size": 256 , 
     "emb_size": 128,
     "attn_hidden_size":512,
     
     "batch_size":16 , 
     'beam_size':4,
     
     "max_enc_len": 400, 
     'max_dec_len':100, 
     'min_dec_steps':35, 
     'max_dec_steps':100,
     
      
     "pointer_gen":True, 
     "coverage":True,
     
     "training":True, 
     'decode':False, 
     'eval' : False,

     
     'vocab_size':50000, 
     
     'examples_max_buffer_len' : 40, 
     'batch_max_buffer_len': 10,
     'max_batch_bucket_len':100 ,
     
     'finished':False, 
     'singlepass':True, 
     
     'max_grad_norm':0.8,
     'adagrad_init_acc':0.1, 
     'learning_rate':0.15, 
     'rand_unif_init_mag':0.02, 
     'trunc_norm_init_std':1e-4,
     'cov_loss_weight':1.0
     }


vocab_path = "<path_to_vocab>/vocab"
data_path = "<path_to_chunks>/train/*"
checkpoint_dir = "checkpoints/"
model_path = "checkpoints/model.ckpt-16" # just an example
training_steps = 20

tf.logging.info('Vocab and Batcher creation')
vocab = Vocab(vocab_path, hpm['vocab_size'])
batcher = Batcher(data_path, hpm, vocab)


def build_graph():
  tf.reset_default_graph()
  tf.logging.info('Building the model.')
  if hpm['decode']:
    hpm['max_dec_len'] = 1
  mod = SummarizationModel(hpm)
  tf.logging.info('Building the graph.')
  mod.add_placeholder()

  device = "/gpu:0" if tf.test.is_gpu_available() else "/cpu:0"
  with tf.device(device):
    mod.build_graph()
  if hpm['training'] or hpm['eval']:
    tf.logging.info('Adding training ops.')
    mod.add_loss()
    mod.add_train_op(device)
  if hpm['decode']:
    assert mod.hpm['batch_size'] == mod.hpm['beam_size']
    mod.add_top_k_likely_outputs()
  return mod



def main():
  
  mod = build_graph()
  
  if hpm['eval']:
    pass

  if hpm['decode']:
    s = tf.Session(config=get_config())
    restore_model(s, hpm, model_path=model_path, check_path = checkpoint_dir)
    #return mod.beam_decode(s, batcher.next_batch(), vocab)
    # and then we can call the beam_decode of the model to decode  th summary (will be implemented later)

  if hpm['training']:
    tf.logging.info('Starting training.')
    try:
      run_training(mod, batcher, hpm, training_steps)
    except KeyboardInterrupt:
      tf.logging.info('stop training.')

if __name__ == '__main__':
  main()
