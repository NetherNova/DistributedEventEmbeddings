import tensorflow as tf
import numpy as np
import math
import pickle


def dot_similarity(x, y, broadcast=False, expand=False):
    """
    Dot similarity across batch
    :param x:
    :param y:
    :return:
    """
    return tf.batch_matmul(x, y)


def dot(x, y):
    return tf.reduce_sum(tf.mul(x, y), 1, keep_dims=True)


def l2_similarity(x, y, broadcast=False, expand=True):
    """
    L2 similairty across batch
    :param x:
    :param y:
    :return:
    """
    if broadcast:
        if expand:
            x = tf.expand_dims(x, 1)
            diff = x - y
        else:
            diff = x - y
            diff = tf.transpose(diff, [1,0,2])
        return -tf.sqrt(tf.reduce_sum(diff ** 2, axis=2))
    else:
        diff = x - y
        return -tf.sqrt(tf.reduce_sum(diff ** 2, axis=1))


def l1_similarity(x, y):
    return - tf.reduce_sum(tf.abs(x - y))


def rescal_similarity(x, y):
    pass


def trans(x, y):
    return x+y


def ident_entity(x, y):
    return x


def max_margin(pos, neg, marge=1.0):
    cost = 1. - pos + neg
    return tf.reduce_mean(tf.maximum(0., cost))


def normalize(W):
    return W / tf.expand_dims(tf.sqrt(tf.reduce_sum(W ** 2, axis=1)), 1)


def rank_left_fn_idx(simfn, embeddings_ent, embeddings_rel, leftop, rightop, inpr, inpo):
    """
    compute similarity score of all 'left' entities given 'right' and 'rel' members
    return *batch_size* rank lists for all entities [all_entities, batch_size] similarity
    :param simfn:
    :param embeddings_ent:
    :param embeddings_rel:
    :param leftop:
    :param rightop:
    :param inpr:
    :param inpo:
    :return:
    """
    lhs = embeddings_ent # [num_entities, d]
    rell = tf.nn.embedding_lookup(embeddings_rel, inpo) # [num_test, d], RESCAL : [num_test, d, d]
    rhs = tf.nn.embedding_lookup(embeddings_ent, inpr) # [num_test, d]
    expanded_lhs = tf.expand_dims(lhs, 1) # [num_ents, 1, d]
    if simfn == l2_similarity:
        batch_lhs = tf.transpose(leftop(expanded_lhs, rell), [0, 1, 2])
        simi = simfn(batch_lhs, rhs, broadcast=True, expand=False)
    elif simfn == rescal_similarity:
        # TODO: only use unique relations in rell / do in loop for rescal outside of TF
        expanded_lhs = tf.expand_dims(expanded_lhs, 2) # [entity_size, 1, 1, d] # TODO: was ist zeile und was ist Spalte in rell?
        # [entity_size, test_size, d]
        expanded_lhs = tf.reduce_sum(tf.mul(expanded_lhs, rell), 3) # TODO: which dim to reduce? 2 or 3
        # [entity_size, test_size, d] * [test_size, d]
        simi = tf.nn.sigmoid(tf.transpose(tf.reduce_sum(tf.mul(expanded_lhs, rhs), 2)))
    else:
        batch_lhs = tf.transpose(leftop(expanded_lhs, rell), [1, 0, 2])
        batch_rhs = tf.transpose(tf.expand_dims(rhs, 1), [0, 2, 1])
        simi = tf.squeeze(simfn(batch_lhs, batch_rhs), 2)
    return simi


def rank_right_fn_idx(simfn, embeddings_ent, embeddings_rel, leftop, rightop, inpl, inpo):
    """
    compute similarity score of all 'right' entities given 'left' and 'rel' members (test_size)
    :param simfn:
    :param embeddings_ent:
    :param embeddings_rel:
    :param leftop:
    :param rightop:
    :return:
    """
    rhs = embeddings_ent
    rell = tf.nn.embedding_lookup(embeddings_rel, inpo)
    lhs = tf.nn.embedding_lookup(embeddings_ent, inpl)
    if simfn == rescal_similarity:
        lhs = tf.expand_dims(lhs, 1)
        # [test_size, 1, d]
        lhs = tf.expand_dims(tf.reduce_sum(tf.mul(lhs, rell), 2), 1)
        # [test_size, 1, d] x [entity, d]
        simi = tf.reduce_sum(tf.mul(lhs, rhs), 2)
        return tf.nn.sigmoid(simi)
    elif simfn == dot_similarity:
        rhs = tf.transpose(rhs)
    simi = simfn(leftop(lhs, rell), rhs, broadcast=True)
    return simi


class SuppliedEmbedding(object):
    def __init__(self, W, dictionary):
        self._W = W
        self._dictionary = dictionary

    def get_embeddings(self):
        return self._W

    def get_dictionary(self):
        return self._dictionary

    def save_embedding(self, file_name):
        pickle.dump(self, open(file_name, "wb"))


class Softmax(object):
    def __init__(self, context, labels, vocabulary_size, negative_sample_size, hidden_dim):
        """ Class needs input of sequence activaction vector,
        the context embeddings (previous lookup) and the actual labels
        :param context:
        :param labels:
        :param vocabulary_size:
        :param negative_sample_size:
        :param hidden_dim:
        """
        self._context = context
        self._labels = labels
        self._vocabulary_size = vocabulary_size
        self._negative_sample_size = negative_sample_size
        self._nce_weights = tf.Variable(tf.truncated_normal([vocabulary_size, hidden_dim],
                      stddev=1.0 / math.sqrt(hidden_dim)))
        self._nce_biases = tf.Variable(tf.zeros([vocabulary_size]))

    def loss(self):
        return tf.reduce_mean(tf.nn.nce_loss(self._nce_weights, self._nce_biases, self._context, self._labels,
                                             self._negative_sample_size, self._vocabulary_size))


class SkipgramModel(object):
    def __init__(self, label, num_entities, num_hidden, num_hidden_softmax):
        self.num_dim = num_hidden
        self.num_entities = num_entities
        self.num_hidden_softmax = num_hidden_softmax
        self.W = tf.Variable(tf.truncated_normal(shape=(num_entities, num_hidden), name="W-"+label))

    def loss(self, lookup_entities, labels):
        # TODO: embedding_lookup, sum over context
        # concatentation of previous layer --> num_hidden_softmax needs to be the size of the concatentation
        context_embeddings = tf.nn.embedding_lookup(self.W, lookup_entities)
        loss = Softmax(context_embeddings, labels, self.num_entities, self.num_hidden_softmax).loss()
        return loss

    def get_normalized_embeddings(self):
        return self.W / tf.sqrt(tf.reduce_sum(tf.square(self.W), 1, keep_dims=True))

    def get_embeddings(self):
        return self.W     


class EventsWithWordsModel(object):
    def __init__(self, len_sequence, num_words_per_sequence, num_entities, embedding_size, num_label_entities, num_neg_samples):
        self._len_sequence = len_sequence
        self._num_words_per_sequence = num_words_per_sequence
        self._num_entities = num_entities
        self._embedding_size = embedding_size
        self._num_label_entities = num_label_entities
        self._num_neg_samples = num_neg_samples
        self.W = EmbeddingLayer("EventWords", num_entities, embedding_size)

    def loss(self, train_dataset, train_labels, batch_size):
        concat = incremental_concat_layer(self.W.get_embeddings(), train_dataset, batch_size, self._embedding_size,
                                          self._len_sequence, self._num_words_per_sequence)
        loss = Softmax(concat, train_labels, self._num_label_entities, self._num_neg_samples, (self._len_sequence) *
                       (self._num_words_per_sequence+1) * self._embedding_size).loss()
        return loss


class EventsWithWordsAndVariantModel(object):
    def __init__(self, len_sequence, num_words_per_sequence, num_entities, embedding_size, num_label_events, num_label_variants, variant_index, num_neg_samples):
        self._len_sequence = len_sequence
        self._num_words_per_sequence = num_words_per_sequence
        self._num_entities = num_entities
        self._embedding_size = embedding_size
        self._num_label_events = num_label_events
        self._num_label_variants = num_label_variants
        self._num_neg_samples = num_neg_samples
        self._variant_index = variant_index
        self.W = EmbeddingLayer("EventWords", num_entities, embedding_size)

    def loss(self, train_dataset, train_labels_events, train_labels_variants, batch_size):
        concat = incremental_concat_layer(self.W.get_embeddings(), train_dataset, batch_size, self._embedding_size,
                                          self._len_sequence, self._num_words_per_sequence)
        variant_embeddings = tf.reshape(tf.nn.embedding_lookup(self.W.get_embeddings(), tf.slice(train_dataset,
                                [0, self._variant_index], [batch_size, 1])), [batch_size, self._embedding_size])
        concat_variant = concat_layer(concat, variant_embeddings)
        concat_last_event = concat_layer(concat, tf.reshape(tf.nn.embedding_lookup(self.W.get_embeddings(),
                                                                                   train_labels_events), [batch_size, self._embedding_size]))
        loss1 = Softmax(concat_variant, train_labels_events, self._num_label_events, self._num_neg_samples,
                        (self._len_sequence) * (self._num_words_per_sequence+1) * self._embedding_size +
                        self._embedding_size).loss()
        loss2 = Softmax(concat_last_event, train_labels_variants, self._num_label_variants, self._num_neg_samples - 3,
                        (self._len_sequence) * (self._num_words_per_sequence+1) * self._embedding_size +
                        self._embedding_size).loss()
        return loss1 + loss2

    def get_model(self, train_dataset, dataset_size):
        concat = incremental_concat_layer(self.W.get_embeddings(), train_dataset, dataset_size, self._embedding_size,
                                          self._len_sequence, self._num_words_per_sequence)
        variant_embeddings = tf.reshape(tf.nn.embedding_lookup(self.W.get_embeddings(), tf.slice(train_dataset,
                            [0, self._variant_index], [dataset_size, 1])), [dataset_size, self._embedding_size])
        concat_variant = concat_layer(concat, variant_embeddings)
        return concat_variant

    def get_embeddings(self, dataset):
        return self.W.get_embeddings()
    

class EventsWithWordsAndVariantComposedModel(object):
    def __init__(self, len_sequence, num_words_per_sequence, num_entities, embedding_size, num_label_events,
                 num_label_variants, variant_index, num_neg_samples, num_variant_parts):
        self._len_sequence = len_sequence
        self._num_words_per_sequence = num_words_per_sequence
        self._num_entities = num_entities
        self._embedding_size = embedding_size
        self._num_label_events = num_label_events
        self._num_label_variants = num_label_variants
        self._num_neg_samples = num_neg_samples
        self._variant_index = variant_index
        self._num_variant_parts = num_variant_parts
        self.W = EmbeddingLayer("EventWords", num_entities, embedding_size)

    def loss(self, train_dataset, train_labels_events, train_labels_variants, batch_size):
        # last entries in train_dataset (..., variant, part, part, ..., part)
        concat = incremental_concat_layer(self.W.get_embeddings(), train_dataset, batch_size,
                                          self._embedding_size, self._len_sequence, self._num_words_per_sequence)
        var_avg = average_layer(tf.nn.embedding_lookup(self.W.get_embeddings(), tf.slice(train_dataset,
                                            [0, self._variant_index], [batch_size, self._num_variant_parts])), axis=1)
        concat_variant_parts = concat_layer(concat, var_avg)
        concat_last_event = concat_layer(concat, tf.reshape(tf.nn.embedding_lookup(self.W.get_embeddings(),
                                                        train_labels_events), [batch_size, self._embedding_size]))
        loss1 = Softmax(concat_variant_parts, train_labels_events, self._num_label_events, self._num_neg_samples,
                        (self._len_sequence) * (self._num_words_per_sequence+1) * self._embedding_size +
                        self._embedding_size).loss()
        loss2 = Softmax(concat_last_event, train_labels_variants, self._num_label_variants, self._num_neg_samples - 3,
                        (self._len_sequence) * (self._num_words_per_sequence+1) * self._embedding_size +
                        self._embedding_size).loss()
        return loss1 + loss2

    def get_model(self, train_dataset, dataset_size):
        concat = incremental_concat_layer(self.W.get_embeddings(), train_dataset, dataset_size, self._embedding_size,
                                          self._len_sequence, self._num_words_per_sequence)
        var_avg = average_layer(tf.nn.embedding_lookup(self.W.get_embeddings(), tf.slice(train_dataset,
                            [0, self._variant_index], [dataset_size, self._num_variant_parts])), axis=1)
        concat_variant_parts = concat_layer(concat, var_avg)
        return concat_variant_parts

    def get_embeddings(self, dataset):
        return self.W.get_embeddings()


def incremental_concat_layer(embeddings, train_dataset, batch_size, embedding_size, len_sequence,
                             num_words_per_sequence):
    """Deprecated: simply use tf.reshape()"""
    def body(i, x):
        a = tf.reshape(tf.nn.embedding_lookup(embeddings, tf.slice(train_dataset, [0, (num_words_per_sequence+1)*i],
                        [batch_size, (num_words_per_sequence+1)])),
                       [batch_size, (num_words_per_sequence+1)*embedding_size])
        return i+1, tf.concat(1, [x, a])

    def condition(i, x):
        return i < len_sequence
    
    i = tf.constant(1)
    init = tf.reshape(tf.nn.embedding_lookup(embeddings, tf.slice(train_dataset, [0,0], [batch_size,
                            (num_words_per_sequence+1)])), [batch_size, (num_words_per_sequence+1)*embedding_size])
    _, result = tf.while_loop(condition, body, [i, init],
                              shape_invariants=[i.get_shape(), tf.TensorShape([None, None])])
    return tf.reshape(result, [batch_size, len_sequence*(num_words_per_sequence+1)*embedding_size])


def concat_layer(left, right):
    """
    Concat two layers alongside axis 1
    :param left:
    :param right:
    :return:
    """
    return tf.concat(1, [left, right])


def average_layer(tensor, axis):
    """
    for 3-dim tensor with batches --> use axis=1
    :param tensor:
    :param axis:
    :return:
    """
    return tf.reduce_mean(tensor, axis)


class EmbeddingLayer(object):
    def __init__(self, label, num_entities, num_hidden):
        self.W = tf.Variable(tf.truncated_normal(shape=(num_entities, num_hidden), name="W-"+label))

    def get_embeddings(self):
        return self.W


class EventEmbedding(object):
    def __init__(self, label, num_entities, num_events, num_dim):
        self.num_dim = num_dim
        self.num_entities = num_entities
        self.num_events = num_events
        self.W = tf.Variable(tf.truncated_normal(shape=(num_entities, num_dim), name="W-"+label))
        self.W_events = tf.Variable(tf.truncated_normal(shape=(num_events, num_dim), name="W-events"))

    def loss(self, lookup_entity, negative_entity, event_entities):
        embed_pos = tf.nn.embedding_lookup(self.W, lookup_entity)
        embed_neg = tf.nn.embedding_lookup(self.W, negative_entity)
        embed_context = tf.reduce_sum(tf.nn.embedding_lookup(self.W_events, event_entities), 1)
        sim_pos = tf.matmul(embed_pos, tf.transpose(embed_context))
        sim_neg = tf.matmul(embed_neg, tf.transpose(embed_context))
        loss = max_margin(sim_pos, sim_neg).loss() + 0.01*tf.nn.l2_loss(self.W) + 0.01*tf.nn.l2_loss(self.W_events)
        return loss

    def get_normalized_embeddings(self):
        return normalize(self.W)

    def evaluate_cosine_similarity(self, valid_dataset):
        normalized_embeddings = self.get_normalized_embeddings()
        valid_embeddings = tf.nn.embedding_lookup(normalized_embeddings, valid_dataset)
        return tf.matmul(valid_embeddings, tf.transpose(normalized_embeddings))


class RecurrentEventEmbedding(EventEmbedding):
    def __init__(self, label, num_entities, num_dim):
        # here num_entities is only number of variants
        super(RecurrentEventEmbedding, self).__init__(label, num_entities, 0, num_dim)

    def loss(self, lookup_entity, negative_entity, context_entities):
        # cell = tf.nn.rnn_cell.BasicRNNCell(self.num_dim)
        cell = tf.nn.rnn_cell.LSTMCell(self.num_dim)
        # context_embedding = tf.nn.embedding_lookup(self.W, context_entities)
        # context_embedding =tf.unstack(context_embeddings)
        context_embedding = tf.pack(context_entities)
        context_embedding = tf.one_hot(context_embedding, 3)
        context_embedding = tf.unstack(context_embedding)
        outputs, state = tf.nn.rnn(cell, context_embedding, dtype=tf.float32)
        embed_context = state[1] # take last state only
        embed_pos = tf.nn.embedding_lookup(self.W, lookup_entity)
        embed_neg = tf.nn.embedding_lookup(self.W, negative_entity)
        score_pos = tf.matmul(embed_pos, tf.transpose(embed_context))
        score_neg = tf.matmul(embed_neg, tf.transpose(embed_context))

        loss = tf.reduce_mean(tf.maximum(0., 1. - score_pos + score_neg))
        return loss


def skipgram_loss(vocab_size, num_sampled, embed, embedding_size, train_labels):
        nce_weights = tf.Variable(
            tf.truncated_normal([vocab_size, embedding_size],
                                stddev=1.0 / tf.sqrt(tf.constant(embedding_size, dtype=tf.float32))))
        nce_biases = tf.Variable(tf.zeros([vocab_size]))

        skipgram_loss = tf.reduce_mean(
            tf.nn.nce_loss(weights=nce_weights,
                           biases=nce_biases,
                           labels=train_labels,
                           inputs=embed,
                           num_sampled=num_sampled,
                           num_classes=vocab_size,
                           remove_accidental_hits=True))
        return skipgram_loss


def rank_triples_left_right(test_tg, scores_l, scores_r, left_ind, o_ind, right_ind):
    errl = []
    errr = []
    for i, (l, o, r) in enumerate(
            zip(left_ind, o_ind, right_ind)):
        # find those triples that have <*,o,r> and * != l
        rmv_idx_l = [l_rmv for (l_rmv, rel, rhs) in test_tg.all_triples if
                     rel == o and r == rel and l_rmv != l]
        # *l* is the correct index
        scores_l[i, rmv_idx_l] = -np.inf
        errl += [np.argsort(np.argsort(-scores_l[i, :]))[l] + 1]
        # since index start at 0, best possible value is 1
        rmv_idx_r = [r_rmv for (lhs, rel, r_rmv) in test_tg.all_triples if
                     rel == o and lhs == l and r_rmv != r]
        # *l* is the correct index
        scores_r[i, rmv_idx_r] = -np.inf
        errr += [np.argsort(np.argsort(-scores_r[i, :]))[r] + 1]
    return errl, errr