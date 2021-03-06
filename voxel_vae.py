import numpy as np
import sys
import os
import tensorflow as tf
import matplotlib.pyplot as plt
#  This import registers the 3D projection, but is otherwise unused.
# noinspection PyUnresolvedReferences
from mpl_toolkits.mplot3d import Axes3D

LATENT_DIMENSIONS = 10
VOXEL_SPACE_SIZE = 16


class VAE(object):
    def __init__(self, input_shape, latent_dimensions, beta=2.5, batch_size=100, checkpoint_dir=None):
        self.current_best = None
        self.current_episode = None
        self.beta = beta
        self.input_shape = input_shape
        self.batch_size = batch_size
        self.latent_dimensions = latent_dimensions
        # self.enc_in = tf.placeholder(tf.float32, (None,) + input_shape)
        self.enc_in = tf.placeholder(tf.float32, (self.batch_size, ) + input_shape + (1, ))
        kernel = 4
        stride = (2, 2, 2)
        num_filter = 32

        # batch size + spatial shape + channel size
        layer_1 = tf.contrib.layers.conv3d(inputs=self.enc_in, num_outputs=num_filter, stride=stride,
                                           kernel_size=kernel)
        layer_2 = tf.contrib.layers.conv3d(inputs=layer_1, num_outputs=num_filter, stride=stride,
                                           kernel_size=kernel)
        layer_3 = tf.contrib.layers.conv3d(inputs=layer_2, num_outputs=num_filter * 2, stride=stride,
                                           kernel_size=kernel)
        layer_4 = tf.contrib.layers.conv3d(inputs=layer_3, num_outputs=num_filter * 2, stride=stride,
                                           kernel_size=kernel)

        layer_flatten = tf.contrib.layers.flatten(inputs=layer_4)

        layer_idk = tf.contrib.layers.fully_connected(inputs=layer_flatten, num_outputs=256)

        self.mus = tf.contrib.layers.fully_connected(inputs=layer_idk, num_outputs=self.latent_dimensions,
                                                     activation_fn=None)

        self.log_var = tf.contrib.layers.fully_connected(inputs=layer_idk, num_outputs=self.latent_dimensions,
                                                         activation_fn=None)
        epsilons = tf.random_normal(self.mus.shape)
        self.z = self.mus + tf.exp(0.5 * self.log_var) * epsilons

        layer_dense_up_sample = tf.contrib.layers.fully_connected(inputs=self.z,
                                                                  num_outputs=int(np.prod(layer_4.shape[1:])))
        layer_un_flatten = tf.reshape(layer_dense_up_sample, layer_4.shape)

        layer_de_1 = tf.contrib.layers.conv3d_transpose(inputs=layer_un_flatten, num_outputs=num_filter * 2,
                                                        stride=stride,
                                                        kernel_size=kernel)
        layer_de_2 = tf.contrib.layers.conv3d_transpose(inputs=layer_de_1, num_outputs=num_filter * 2, stride=stride,
                                                        kernel_size=kernel)
        layer_de_3 = tf.contrib.layers.conv3d_transpose(inputs=layer_de_2, num_outputs=num_filter, stride=stride,
                                                        kernel_size=kernel)
        layer_de_4 = tf.contrib.layers.conv3d_transpose(inputs=layer_de_3, num_outputs=num_filter, stride=stride,
                                                        kernel_size=kernel)
        self.dec_out = tf.contrib.layers.conv3d_transpose(inputs=layer_de_4, num_outputs=1, stride=1,
                                                          kernel_size=1)
        assert self.enc_in.shape == self.dec_out.shape
        self.optimizer = tf.train.AdamOptimizer()

        kl_loss = 1 + self.log_var - tf.pow(self.mus, 2) - tf.exp(self.log_var)
        kl_loss = -0.5 * tf.reduce_sum(kl_loss, axis=-1)
        reconstruction_err = tf.losses.mean_squared_error(labels=self.enc_in, predictions=self.dec_out)
        reconstruction_err *= np.prod(self.input_shape)
        self.loss = tf.reduce_mean(self.beta * kl_loss + reconstruction_err)

        # reconstruction_err = tf.nn.sigmoid_cross_entropy_with_logits(labels=self.enc_in, logits=self.dec_out)
        # self.loss = tf.reduce_mean(reconstruction_err)

        self.train_op = self.optimizer.minimize(self.loss)
        self.sess = tf.Session()
        self.sess.run(tf.global_variables_initializer())
        self.saver = tf.train.Saver(var_list=tf.global_variables())
        if checkpoint_dir is None:
            self.checkpoint_dir = '{}/chk'.format(os.path.dirname(__file__))
        else:
            self.checkpoint_dir = checkpoint_dir

        # just for dbg prints
        self._train_data_len = None
        self._trained_ep_samples = None
        self._cur_ep_str = None
        self._cur_err = None
        self._cur_loss = None

    def train(self, num_episodes, data, plot_best=False):
        self._train_data_len = len(data)
        if self.current_best is None:
            self._check_dir(self.checkpoint_dir, create_on_fail=True)
            with open('{}/history.csv'.format(self.checkpoint_dir), 'w') as file:
                file.write('train/success_rate,test/success_rate,best\n')
            self.current_best = sys.float_info.max
        if self.current_episode is None:
            self.current_episode = 0
        print('starting with episode %s, training additional %s episodes' % (self.current_episode, num_episodes))
        if plot_best:
            plt.ion()
            fig = plt.figure('Reconstruction')
            ax = fig.gca(projection='3d')
            ax.view_init(24, 144)
            recon = self.full_pass(data[:self.batch_size])[0].reshape((self.batch_size, ) + self.input_shape)
            print('initial: max: %s min: %s mean: %s' % (np.max(recon), np.min(recon), np.mean(recon)))
            ax.voxels(data[0] > 0.5, facecolors=[0, 0, 1, 0.3], edgecolor=[0, 0, 1, 0.0])
            # ax.voxels(recon[0] > 0.5, facecolors=[0, 1, 0, 0.2], edgecolor=[0, 1, 0, 0.5])
            # overlap green
            ax.voxels(np.logical_and(data[0] > 0.5, recon[0] > 0.5), facecolors=[0, 1, 0, 0.0],
                      edgecolor=[0, 1, 0, 0.7])
            # orig only blue
            # ax.voxels(np.logical_and(data[0] > 0.5, recon[0] <= 0.5), facecolors=[0, 0, 1, 0.4],
            # edgecolor=[0, 0, 1, 0.0])
            # recon only red
            ax.voxels(np.logical_and(data[0] <= 0.5, recon[0] > 0.5), facecolors=[1, 0, 0, 0.0],
                      edgecolor=[1, 0, 0, 0.7])
            plt.pause(0.0000001)
        with self.sess as session:
            for i in range(num_episodes):
                print('episode %s of %s' % (self.current_episode, (num_episodes-i+self.current_episode)))
                np.random.shuffle(data)
                for j in range(0, self._train_data_len, self.batch_size):
                    if self._train_data_len > j + self.batch_size:
                        batch = np.expand_dims(data[j:j + self.batch_size], axis=-1)
                        _, loss, dec_out, log_var = session.run([self.train_op, self.loss, self.dec_out, self.log_var],
                                                                feed_dict={self.enc_in: batch})

                        batch = batch.reshape((self.batch_size, ) + self.input_shape)
                        dec_out = dec_out.reshape((self.batch_size, ) + self.input_shape)
                        self._cur_err = '%0.8f' % float(np.sum(np.abs(batch-dec_out))/self.batch_size)
                        self._cur_loss = '%0.8f' % loss

                        self._trained_ep_samples = ('{0:0>%s}' %
                                                    len(str(self._train_data_len))).format(j + self.batch_size)
                        self._cur_ep_str = ('{0:0>%s}' %
                                            len(str(num_episodes-i+self.current_episode))).format(self.current_episode)
                        print(
                            'trained {_trained_ep_samples} of {_train_data_len} samples '
                            'for episode {_cur_ep_str} (loss:{_cur_loss}, err:{_cur_err}'.format(**self.__dict__))
                        print('sigmas:', np.mean(np.exp(0.5 * log_var), axis=0))
                        if loss < self.current_best:
                            self.current_best = loss
                            print('>>>>>>>> new best: %r' % self.current_best)
                            self._save('best', loss=loss, episode=self.current_episode)
                            if plot_best:
                                errs = [np.sum(s) for s in np.sum(np.abs(batch-dec_out), axis=1)]
                                num_vox_orig = [np.sum(s) for s in np.sum(batch, axis=1)]
                                num_vox_recon = [np.sum(s) for s in np.sum(dec_out > 0.5, axis=1)]
                                print(np.max(dec_out))
                                best_idx = int(np.argmin(errs))
                                ax.cla()
                                plt.title('err: %0.3f, orig_vox: %s, rec_vox: %s' %
                                          (errs[best_idx], num_vox_orig[best_idx], num_vox_recon[best_idx]))
                                ax.voxels(batch[best_idx] > 0.5, facecolors=[0, 0, 1, 0.5],
                                          edgecolor=[1, 0, 0, 0.0])
                                 #ax.voxels(dec_out[best_idx] > 0.5, facecolors=[0, 1, 0, 0.2],
                                # edgecolor=[0, 1, 0, 0.5])
                                # overlap green
                                ax.voxels(np.logical_and(batch[best_idx] > 0.5, dec_out[best_idx] > 0.5),
                                          facecolors=[0, 1, 0, 0.0],
                                          edgecolor=[0, 1, 0, 0.9])
                                # orig only blue
                                #ax.voxels(np.logical_and(batch[best_idx] > 0.5, dec_out[best_idx] <= 0.5),
                                # facecolors=[0, 0, 1, 0.4],
                                #          edgecolor=[0, 0, 1, 0.0])
                                # recon only red
                                ax.voxels(np.logical_and(batch[best_idx] <= 0.5, dec_out[best_idx] > 0.5),
                                          facecolors=[1, 0, 0, 0.0],
                                          edgecolor=[1, 0, 0, 0.9])
                                plt.pause(0.0000001)

                        self._save(loss=self._cur_loss, episode=self.current_episode)

                '{0:0{width}}'.format(5, width=3)
                self.current_episode += 1

    def full_pass(self, data):
        batch = np.expand_dims(data, axis=-1)
        return self.sess.run([self.dec_out], feed_dict={self.enc_in: batch})

    def encode(self, data):
        batch = np.expand_dims(data, axis=-1)
        return self.sess.run([self.z], feed_dict={self.enc_in: batch})

    def decode(self, data):
        return self.sess.run([self.dec_out], feed_dict={self.z: data})

    def load(self, load_dir='best'):
        try:
            self._load(load_dir)
        except FileNotFoundError as e:
            print('loading failed:', e)

    def _save(self, save_dir='latest', loss=sys.float_info.max, episode=0):
        path = '{}/{}/'.format(self.checkpoint_dir, save_dir)
        self._check_dir(path, create_on_fail=True)
        self.saver.save(self.sess, path)
        with open('{}loss'.format(path), 'w') as file:
            file.write('%s' % loss)
        with open('{}episode'.format(path), 'w') as file:
            file.write('%s' % episode)
        if save_dir == 'latest':
            with open('{}/history.csv'.format(self.checkpoint_dir), 'a') as file:
                file.write('{},{},{}\n'.format(episode, loss, self.current_best))

    def _load(self, load_dir):
        path = '{}/{}/'.format(self.checkpoint_dir, load_dir)
        self._check_dir(path)
        self.saver.restore(self.sess, path)
        with open('{}loss'.format(path), 'r') as file:
            self.current_best = float(file.readline())
        with open('{}episode'.format(path), 'r') as file:
            self.current_episode = int(file.readline())
        print('loaded from %s (loss:%s)' % ('{}'.format(path), self.current_best))

    @staticmethod
    def _check_dir(path, create_on_fail=False):
        if not os.path.exists(path):
            if create_on_fail:
                os.makedirs(path)
            else:
                raise FileNotFoundError('%r does not exist' % path)

    def __del__(self):
        """ Cleanup after object finalization """
        # close tf.Session
        if hasattr(self, 'sess'):
            self.sess.close()


def train_that_data(voxel_filename):
    _batch_size = 48

    vae = VAE((VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE), LATENT_DIMENSIONS, batch_size=_batch_size)
    train_data = np.load(voxel_filename)
    vae.load()

    vae.train(num_episodes=100, data=train_data, plot_best=True)


def plot_that_data(voxel_filename):

    _batch_size = 100
    display_random_decoded = True

    vae = VAE((VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE), latent_dimensions=LATENT_DIMENSIONS,
              batch_size=_batch_size)
    data = np.load(voxel_filename)
    vae.load()

    data_set = data[:_batch_size]
    results = vae.full_pass(data_set)[0].reshape((_batch_size, VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE, VOXEL_SPACE_SIZE))

    plt.ion()
    fig = plt.figure('Reconstruction')
    ax = fig.gca(projection='3d')
    ax.view_init(24, 144)

    if display_random_decoded:
        random_decoded = vae.decode(np.random.rand(_batch_size,
                                                   vae.latent_dimensions))[0].reshape((_batch_size,
                                                                                       VOXEL_SPACE_SIZE,
                                                                                       VOXEL_SPACE_SIZE,
                                                                                       VOXEL_SPACE_SIZE))
        fig2 = plt.figure('Generative')
        ax2 = fig2.gca(projection='3d')
        ax2.view_init(24, 144)

    for i in range(len(data_set)):

        orig = data_set[i]
        recon = results[i]
        ax.cla()
        ax.voxels(orig > 0.5, facecolors=[1, 0, 0, 0.5], edgecolor=[1, 0, 0, 0.9])
        ax.voxels(recon > 0.5, facecolors=[0, 1, 0, 0.2], edgecolor=[0, 1, 0, 0.5])
        if display_random_decoded:
            ax2.cla()
            ax2.voxels(random_decoded[i] > 0.5, facecolors=[0, 0, 1, 0.5], edgecolor=[0, 0, 1, 0.9])

        print('reconstruction err:', np.sum((orig > 0.5) ^ (recon > 0.5)))
        plt.pause(0.0000000001)

    plt.pause(1)


if __name__ == '__main__':
    # plot_that_data("/home/ffriese/prj-robotic-arms/voxel_vae/transformed voxel_data.npy")
    train_that_data("/home/ffriese/prj-robotic-arms/voxel_vae/transformed voxel_data.npy")