# -*- coding: utf-8 -*-
"""pointer_gen_model.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/11cNRDFW5_4tCVGjX-5L1OTuS7Bi9lq5R
"""

import numpy as np
import random
import tensorflow as tf
import tensorflow.nn as nn

from modules import Encoder
from modules import  Attention_decoder
from utils import _mask_and_avg


class SummarizationModel():
  """
  The pointer generator model
      Args:
          hpm : hyperparameters
  """
  
  def __init__(self, hpm):
    self.hpm = hpm
    
    # parameters initializer objetcs
    self.rand_unif_init = tf.random_uniform_initializer(-self.hpm['rand_unif_init_mag'], self.hpm['rand_unif_init_mag'], seed=123)
    self.rand_norm_init = tf.truncated_normal_initializer(stddev=self.hpm['trunc_norm_init_std'])
    
    # encoder and attentional decoder objects
    self.encoder = Encoder(self.hpm, self.rand_unif_init,  self.rand_norm_init)
    self.decoder = Attention_decoder(self.hpm, self.rand_unif_init, self.rand_norm_init)
    
    # a global step counter for the training
    self.step = tf.train.get_or_create_global_step()
      
      
      

  def add_placeholder(self):
    """ Adding placeholders to the model """
    
    with tf.variable_scope("placeholder"):
      self.enc_batch = tf.placeholder(tf.int32, [self.hpm['batch_size'], None], name='enc_batch') # encoder input sequences (the 2nd dimension -max_enc_len-
                                                                                                  # of the shape is None because it varies with the batch)
      self.enc_mask = tf.placeholder(tf.float32, [self.hpm['batch_size'], None], name='enc_mask') # encoder input sequences masks
      self.enc_lens = tf.placeholder(tf.int32, [self.hpm['batch_size']], 'enc_lens')  # lengths of the input sequences 

      if self.hpm['pointer_gen']:
        self.enc_extend_vocab = tf.placeholder(tf.int32, [self.hpm['batch_size'], None], 'enc_extend_vocab') # encoder input sequences with oovs ids
        self.max_art_oovs = tf.placeholder(tf.int32, [], 'max_art_oovs') # maximum number of oovs for the current batch
      
      self.dec_batch = tf.placeholder(tf.int32, [self.hpm['batch_size'], self.hpm['max_dec_len']], name='dec_batch') # decoder input sequences (max_dec_len = 1 in decode mode)
      self.dec_target = tf.placeholder(tf.int32, [self.hpm['batch_size'], self.hpm['max_dec_len']], name='target_batch')
      self.dec_mask = tf.placeholder(tf.float32, [self.hpm['batch_size'], self.hpm['max_dec_len']], name='dec_mask') # decoder input masks tensors
      

      
      
      
  def build_graph(self):
    """ Graph building method"""
    with tf.variable_scope("embedding"):

      inp_embed = tf.get_variable('inp_embed', [self.hpm['vocab_size'], self.hpm['emb_size']], dtype=tf.float32) # encoder input embeddings
      dec_embed = tf.get_variable('dec_embed', [self.hpm['vocab_size'], self.hpm['emb_size']], dtype=tf.float32) # decoder input embeddings
      
    # we lookup the encoder input in the embedding matrix
    inps =  tf.nn.embedding_lookup(inp_embed, self.enc_batch) # shape : [batch_size, <batch_max_enc_len>, embed_size]
    # we lookup the decoder input in the embedding matrix
    dec = tf.transpose(self.dec_batch, perm=[1,0])
    dec_inps = tf.nn.embedding_lookup(dec_embed, dec) # shape : [max_dec_len, batch_size, embed_size]
    # we add the encoder ops
    self.enc_outputs, self.dec_state = self.encoder(inps, self.enc_lens)
    
    

    self.cov_vec = tf.zeros(shape=[self.hpm['batch_size'],tf.shape(self.enc_outputs)[1] ] , dtype=tf.float32, name="cov_vec")
    # we add the decoder ops
    self.enc_outputs = tf.identity(self.enc_outputs, "enc_outputs")
    self.dec_state = tf.identity(self.dec_state, "dec_state")
    self.dec_state = tf.contrib.rnn.LSTMStateTuple(self.dec_state[0],self.dec_state[1])

    self.returns = self.decoder(self.enc_outputs, self.enc_mask,self.dec_state, dec_inps, self.max_art_oovs , self.enc_extend_vocab, self.cov_vec)

    self.returns['last_context_vector'] = tf.identity(self.returns['last_context_vector'],name="last_context_vector")

    self.returns['attention_vec'] = tf.identity(self.returns['attention_vec'], name="attention_vec")

    #self.returns['coverage']  = tf.identity(self.returns['coverage'] , name="coverage")
    self.returns['p_gen'] = tf.identity(self.returns['p_gen'], name="p_gen")
    
    self.returns['coverage'] = tf.identity(self.returns['coverage'], "coverage")

    self.returns['dec_state'] = tf.identity(self.returns['dec_state'], 'new_dec_state')
    self.returns['dec_state'] = tf.contrib.rnn.LSTMStateTuple(self.returns['dec_state'][0], self.returns['dec_state'][1])

    self.returns['output'] = tf.identity(self.returns['output'], "logits")

    if  self.hpm['decode_using_prev']:
      self.returns['argmax_seqs'] = tf.identity(self.returns['argmax_seqs'], "argmax_seqs")
      self.returns['argmax_log_probs'] = tf.identity(self.returns['argmax_log_probs'], "argmax_log_probs")
      self.returns['samples_seqs'] = tf.identity(self.returns['samples_seqs'], "samples_seqs")
      self.returns['samples_log_probs'] = tf.identity(self.returns['samples_log_probs'], "samples_log_probs")


    


  def make_feed_dict(self, batch):
    """
        Args:
            batch : Batch Object
        Return:
            A dictionary to feed the model during training
    """
    feed_dict = {}

    feed_dict[self.enc_batch] = batch.enc_batch
    feed_dict[self.enc_mask] = batch.enc_padding_mask
    feed_dict[self.enc_lens] = batch.enc_lens

    if self.hpm['pointer_gen']:
      feed_dict[self.enc_extend_vocab] = batch.enc_batch_extend_vocab
      feed_dict[self.max_art_oovs] = batch.max_art_oovs
      
    feed_dict[self.dec_batch] = batch.dec_batch
    feed_dict[self.dec_target] = batch.target_batch
    feed_dict[self.dec_mask] = batch.dec_padding_mask

    return feed_dict
  
  
  
  def add_loss(self):
    """ We add the loss computation op """
    with tf.variable_scope('loss'):
      
      if self.hpm['pointer_gen']: #if pointer_gen we apply the cross_entropy function ourselves:
                                  # we compute the log of the predicted probability of the target target word (this is the probability we must maximize)
        loss_per_step = []
        batch_nums = tf.range(0, limit=self.hpm['batch_size']) # shape (batch_size)
        for dec_step, dist in enumerate(tf.unstack(self.returns['output'])):
          targets = self.dec_target[:,dec_step] # The indices of the target words. shape (batch_size)
          indices = tf.stack( (batch_nums, targets), axis=1) # shape (batch_size, 2)
          gold_probs = tf.gather_nd(dist, indices) # shape (batch_size). prob of correct words on this step
          losses = -tf.log(gold_probs)
          loss_per_step.append(losses)
          
        self.loss = _mask_and_avg(loss_per_step, self.dec_mask) # we drop the loss of the pad tokens
        
      else:
        self.loss = tf.contrib.seq2seq.sequence_loss(tf.stack(self.returns['output'], axis=1), self.dec_batch, self.dec_mask)
        #if not pointer_gen, we compute the softmax, and the sequence to squence cross_entropy loss with this helper function
      
      tf.summary.scalar('loss', self.loss)
      self.total_loss = self.loss
      if self.hpm['coverage']:
        
          # nested function
        def coverage_loss(self):
          """ coverage loss computation"""
          covlosses = []
          coverage = tf.zeros_like(tf.unstack(self.returns['attention_vec'][0]))
          for a in tf.unstack(self.returns['attention_vec']): # a in an attention vector at time step t
            covloss = tf.reduce_sum(tf.minimum(a, coverage ), 1) 
            covlosses.append(covloss)
            coverage += a
          coverage_loss = _mask_and_avg(covlosses, self.enc_mask) # we drop the pad tokens loss and compute the avg loss
          return coverage_loss
 
        self.coverage_loss = coverage_loss(self)
        self.coverage_loss = tf.identity(self.coverage_loss, name="coverage_loss")
        if self.hpm['add_coverage']:
          tf.summary.scalar('coverage_loss', self.coverage_loss)
        if self.hpm['add_coverage']:
          self.total_loss += self.hpm['cov_loss_weight']* self.coverage_loss # we weight the coverage loss and add it to thhe total loss
        # the total loss = seq2seq_loss + coverage_loss (if coverage = True)
        tf.summary.scalar('total_loss', self.total_loss)

        self.loss = tf.identity(self.loss, name="loss")
        self.total_loss = tf.identity(self.total_loss, name="total_loss")
  
  
  
  def add_train_op(self, device):
    """We add the training op to the graph"""
    loss_to_minimize = self.total_loss
    variables = tf.trainable_variables() # we recover all the trainable parameters
    gradients = tf.gradients(loss_to_minimize, variables, aggregation_method=tf.AggregationMethod.EXPERIMENTAL_TREE ) # we compute the gradients of the loss with respect to all the parameters (backpropagation)
    
    with tf.device(device):
      grads, global_norm = tf.clip_by_global_norm(gradients, self.hpm['max_grad_norm']) # we clip the gradients
    
    optimizer = tf.train.AdagradOptimizer(self.hpm['learning_rate'], initial_accumulator_value=self.hpm['adagrad_init_acc'], ) # we create the optimizer object
    with tf.device(device):
      self.train_op = optimizer.apply_gradients(zip(grads, variables), name='train_step', global_step=self.step) # Gradient descent (we update the parameters)
      # this is the training op

    self.summaries = tf.summary.merge_all()
      
      
      
  def setSession(self, sess):
    """ we set a session for the training"""
    self.sess = sess
      
  
  
  def train(self, batch):
    """We run the train op"""
    feed_dict = self.make_feed_dict(batch)
    to_return = {'train_op':self.train_op,
                'loss':self.loss,
                'global_step':self.step,
                 'summaries' : self.summaries}
    if (self.hpm['coverage']):
      to_return['coverage_loss'] = self.coverage_loss
      
      return self.sess.run(to_return, feed_dict)
    
    
   
  
  def add_top_k_likely_outputs(self):
    """We add an op to the graph that computes the top k output probabilities and their ids, used during decoding"""
    assert len(tf.unstack(self.returns['output'])) == 1
    top_k_probs, self.top_k_ids= tf.nn.top_k(self.returns['output'][0], self.hpm['beam_size']*2)
    self.top_k_log_probs = tf.log(top_k_probs, name="top_k_log_probs")
    self.top_k_ids = tf.identity(self.top_k_ids, name="top_k_ids")
    # we compute the log of the probalities (given the size of the vocabulary, the probaility are generally very small, it is better then to use their log)
    


  def add_prob_logits_samples(self):
    outputs = tf.unstack(self.returns['output'])
    batch_nums = tf.range(0, limit=self.hpm['batch_size'], dtype=tf.int64)
    argmax_seqs = []
    argmax_seqs_log_probs = []
    for i , x in enumerate(outputs):
      max_ids = tf.argmax(x, axis=-1)
      indices = tf.stack((batch_nums, max_ids), axis = -1)
      log_probs = tf.gather_nd(x, indices)
      argmax_seqs.append(max_ids)
      argmax_seqs_log_probs.append(log_probs)


    self.outputs = self.returns['output']
    if not self.hpm['pointer_gen']:
      self.outputs = tf.softmax(self.outputs)

    self.argmax_seqs = tf.stack(argmax_seqs, name='argmax_seqs')
    self.argmax_seqs_log_probs = tf.stack(argmax_seqs_log_probs, name='argmax_seqs_log_probs')

    sampler = tf.distributions.Categorical(logits=outputs)
    self.samples = sampler.sample(name='samples')
    self.samples = tf.identity(self.samples, name='samples')
    self.samples_log_probs = sampler.log_prob(self.samples, name="samples_log_probs")
    self.samples_log_probs = tf.identity(self.samples_log_probs, name="samples_log_probs")

  
  
  def decode_onestep(self, sess, batch, enc_outputs, dec_state, dec_input, cov_vec):
    """
        Method to decode the output step by step (used for beamSearch decoding)
        Args:
            sess : tf.Session object
            batch : current batch, shape = [beam_size, 1, vocab_size( + max_oov_len if pointer_gen)] (for the beam search decoding, batch_size = beam_size)
            enc_outputs : hiddens outputs computed by the encoder LSTM
            dec_state : beam_size-many list of decoder previous state, LSTMStateTuple objects, shape = [beam_size, 2, hidden_size]
            dec_input : decoder_input, the previous decoded batch_size-many words, shape = [beam_size, embed_size]
            cov_vec : beam_size-many list of previous coverage vector
        Returns: A dictionary of the results of all the ops computations (see below for more details)
    """
    
    # dec_state is a batch_size-many list of LSTMStateTuple objects
    # we have to transform it to one LSTMStateTuple object where c and h have shape : [beam_size, hidden_size]
    cells = [np.expand_dims(state.c, axis=0) for state in dec_state] 
    hiddens = [np.expand_dims(state.h, axis=0) for state in dec_state]
    new_c = np.concatenate(cells, axis=0)
    new_h = np.concatenate(hiddens, axis=0)
    new_dec_in_state = tf.contrib.rnn.LSTMStateTuple(new_c, new_h)
    
    # dictionary of all the ops that will be computed
    to_return = {'last_context_vector' : self.returns['last_context_vector'], # list of the previous context_vectors , shape : [beam_size, 2 x hidden_size]
                'dec_state' : self.returns['dec_state'], # beam_size-many list of LSTMStateTuple cells, where c and h have shape : [hidden_size]
                'top_k_ids' : self.top_k_ids, # top (2x xbeam_size) ids of the most liikely words to appear at the current time step
                'top_k_log_probs' : self.top_k_log_probs, # top (2x xbeam_size) probabilities of the most liikely words to appear at the current time step
                'attention_vec':self.returns['attention_vec']} # beam_size-many list of attention vectors, shape : [1, beam_size, max_enc_len]
 
    if self.hpm['coverage']:
      to_return['coverage'] = self.returns['coverage'] # beam_size-many list of coverage vectors , shape : [batch_size, max_enc_len]
    if self.hpm['pointer_gen']:
      to_return['p_gen'] = self.returns['p_gen'] # shape : [beam_size, 1]
        
    to_feed = {self.enc_outputs : enc_outputs,
              self.enc_mask : batch.enc_padding_mask,
              self.dec_batch : np.transpose(np.array([dec_input])), #shape : [beam_size, 1]
              self.dec_state : new_dec_in_state}

    if self.hpm['pointer_gen']:
      to_feed[self.enc_extend_vocab] = batch.enc_batch_extend_vocab
      to_feed[self.max_art_oovs] = batch.max_art_oovs

    if self.hpm['coverage']:
      to_feed[self.cov_vec] = cov_vec
        
    results =  sess.run(to_return, to_feed)
    states = results['dec_state']
    results['dec_state'] = [tf.contrib.rnn.LSTMStateTuple(states.c[i,:], states.h[i,:]) for i in range(self.hpm['beam_size'])]
    #we transform dec_state into a list of LSTMStateTuple objects, an LSTMStateTuple for each likely word
    
    return results
  
  
  def beam_decode(self, sess, batch, vocab):
    
    # nested class
    class Hypothesis:
      """ Class designed to hold hypothesises throughout the beamSearch decoding """
      def __init__(self, tokens, log_probs, state, attn_dists, p_gens, coverage):
        self.tokens = tokens # list of all the tokens from time 0 to the current time step t
        self.log_probs = log_probs # list of the log probabilities of the tokens of the tokens
        self.state = state # decoder state after the last token decoding
        self.attn_dists = attn_dists # attention dists of all the tokens
        self.p_gens = p_gens # generation probability of all the tokens
        self.coverage = coverage # coverage at the current time step t

      def extend(self, token, log_prob, state, attn_dist, p_gen, coverage):
        """Method to extend the current hypothesis by adding the next decoded toekn and all the informations associated with it"""
        return Hypothesis(tokens = self.tokens + [token], # we add the decoded token
                          log_probs = self.log_probs + [log_prob], # we add the log prob of the decoded token
                          state = state, # we update the state
                          attn_dists = self.attn_dists + [attn_dist], # we  add the attention dist of the decoded token
                          p_gens = self.p_gens + [p_gen], # we add the p_gen 
                          coverage = coverage) # we update the coverage

      @property
      def latest_token(self):
        return self.tokens[-1]

      @property
      def tot_log_prob(self):
        return sum(self.log_probs)

      @property
      def avg_log_prob(self):
        return self.tot_log_prob/len(self.tokens)

    # end of the nested class

    # We run the encoder once and then we use the results to decode each time step token
    enc_outputs, dec_in_state = sess.run([self.enc_outputs, self.dec_state], {self.enc_batch : batch.enc_batch,
                                                    self.enc_mask : batch.enc_padding_mask,
                                                    self.enc_lens : batch.enc_lens})
    # Initial Hypothesises (beam_size many list)
    hyps = [Hypothesis(tokens=[vocab.word_to_id('[START]')], # we initalize all the beam_size hypothesises with the token start
                      log_probs = [0.0], # Initial log prob = 0
                      state = tf.contrib.rnn.LSTMStateTuple(dec_in_state.c[0], dec_in_state.h[0]), #initial dec_state (we will use only the first dec_state because they're initially the same)
                      attn_dists=[],
                      p_gens = [],
                      coverage=np.zeros([enc_outputs.shape[1]]) # we init the coverage vector to zero
                      ) for _ in range(self.hpm['batch_size'])] # batch_size == beam_size
    
    results = [] # list to hold the top beam_size hypothesises
    steps=0 # initial step
    
    while steps < self.hpm['max_dec_steps'] and len(results) < self.hpm['beam_size'] : 
      latest_tokens = [h.latest_token for h in hyps] # latest token for each hypothesis , shape : [beam_size]
      latest_tokens = [t if t in range(self.hpm['vocab_size']) else vocab.word_to_id('[UNK]') for t in latest_tokens] # we replace all the oov is by the unknown token
      states = [h.state for h in hyps] # we collect the last states for each hypothesis
      
      if self.hpm['coverage']:
        prev_coverage = [h.coverage for h in hyps]
      else:
        prev_coverage = None
      
      # we decode the top likely 2 x beam_size tokens tokens at time step t for each hypothesis
      returns = self.decode_onestep(sess, batch, enc_outputs, states, latest_tokens, prev_coverage)
      topk_ids, topk_log_probs, new_states, attn_dists =  returns['top_k_ids'], returns['top_k_log_probs'], returns['dec_state'], returns['attention_vec']
      if self.hpm['pointer_gen']:
        p_gens = returns['p_gen']
      if self.hpm['coverage']:
        new_coverage = returns['coverage']
        
      attn_dists = np.squeeze(attn_dists) # shape : [beam_size, max_enc_len]
      if self.hpm['pointer_gen']:
        p_gens = np.squeeze(p_gens) # shape : [beam_size]
      
      all_hyps = []
      num_orig_hyps = 1 if steps ==0 else len(hyps)
      for i in range(num_orig_hyps):
        h, new_state, attn_dist, p_gen, new_coverage_i = hyps[i], new_states[i], attn_dists[i], p_gens[i], new_coverage[i]
        
        for j in range(self.hpm['beam_size']*2):
          # we extend each hypothesis with each of the top k tokens (this gives 2 x beam_size new hypothesises for each of the beam_size old hypothesises)
          new_hyp = h.extend(token=topk_ids[i,j],
                             log_prob=topk_log_probs[i,j],
                             state = new_state,
                             attn_dist=attn_dist,
                             p_gen=p_gen,
                            coverage=new_coverage_i)
          all_hyps.append(new_hyp)
          
      # in the following lines, we sort all the hypothesises, and select only the beam_size most likely hypothesises
      hyps = []
      sorted_hyps = sorted(all_hyps, key=lambda h: h.avg_log_prob, reverse=True)
      for h in sorted_hyps:
        if h.latest_token == vocab.word_to_id('[STOP]'):
          if steps >= self.hpm['min_dec_steps']:
            results.append(h)
        else:
          hyps.append(h)
        if len(hyps) == self.hpm['beam_size'] or len(results) == self.hpm['beam_size']:
          break
            
      steps += 1
                   
    if len(results)==0:
      results=hyps
    
    # At the end of the loop we return the most likely hypothesis, which holds the most likely ouput sequence, given the input fed to the model
    hyps_sorted = sorted(results, key=lambda h: h.avg_log_prob, reverse=True)
    return hyps_sorted[0]