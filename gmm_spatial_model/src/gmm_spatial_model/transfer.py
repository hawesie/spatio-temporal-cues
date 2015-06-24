#!/usr/bin/env python

import itertools
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

from scipy import linalg
from sklearn import mixture
from matplotlib.colors import LogNorm
from geometry_msgs.msg import Pose, Point, Quaternion 
from tf.transformations import euler_from_quaternion, quaternion_from_euler
from math import cos, sin, radians
from mongodb_store.message_store import MessageStoreProxy
from soma_msgs.msg import SOMAObject
from scipy.spatial.distance import euclidean
from sklearn.metrics import log_loss
import models
import support_functions


def build_relational_models(bad_sample_poses, good_sample_poses, landmarks, transferred_landmarks, relation_fns, server):
    # threshold used to eliminate bad resulting models
    CLASSIFIER_THRESHOLD = 0.2
    
    results = []
    results_for_visualization = []
    model   = None

    for i in xrange(len(landmarks)):
        for relation_name, relation_fn in relation_fns.iteritems():
            bad_relation_metrics = support_functions.to_spatial_relation(landmarks[i].pose, bad_sample_poses, relation_fn)
            good_relation_metrics = support_functions.to_spatial_relation(landmarks[i].pose, good_sample_poses, relation_fn)
            relation_metrics = np.concatenate((bad_relation_metrics, good_relation_metrics))


            # create the mixture model
            classifier = mixture.GMM(n_components=2, covariance_type='full', init_params='wc')
            # we can initialise the means based on our knowledge of the good/bad samples
            # this is from http://scikit-learn.org/stable/auto_examples/mixture/plot_gmm_classifier.html#example-mixture-plot-gmm-classifier-py
            classifier.means_ = np.array([bad_relation_metrics.mean(axis=0), good_relation_metrics.mean(axis=0)]) 

            # fit to data, starting from these means
            classifier.fit(relation_metrics)
            # use the built classifier to predict classifiers for our training data
            predictions = classifier.predict_proba(relation_metrics)
            # and see how good it is on the data
            classifier_loss = log_loss([0] * len(bad_relation_metrics) + [1] * len(good_relation_metrics), predictions)

            print 'point %s %s: %s' % (relation_name, landmarks[i].type, classifier_loss)
            print 'classifier obtained for relation %s %s: components = %s, weights = %s, means = %s, covars = %s'%(landmarks[i].type, relation_name, classifier.n_components, classifier.weights_, classifier.means_, classifier.covars_)
            
            # discards bad models based on the classifier loss
            if classifier_loss >= CLASSIFIER_THRESHOLD:
                continue

            old_model   = models.TransferModel(landmarks[i], classifier, classifier_loss, relation_name)
            model       = models.TransferModel(transferred_landmarks[i], classifier, classifier_loss, relation_name)

            results.append(model)

            #map_width = 10
            #pcloud = support_functions.model_to_pc2(old_model, landmarks[i].pose.position.x - map_width / 2, landmarks[i].pose.position.y - map_width / 2, 0.04, map_width, map_width)
            #server.model_cloud.publish(pcloud)

            #raw_input("Showing old model...")

            #map_width = 10
            #pcloud = support_functions.model_to_pc2(model, transferred_landmarks[i].pose.position.x - map_width / 2, transferred_landmarks[i].pose.position.y - map_width / 2, 0.04, map_width, map_width)
            #server.model_cloud.publish(pcloud)

            #raw_input("Showing new model...")


    return results


def visualise_relations(target, landmarks, bad_sample_poses, good_sample_poses, classifier_results):
    # to just x,y 
    good_samples = support_functions.pose_list_to_np(good_sample_poses)
    bad_samples = support_functions.pose_list_to_np(bad_sample_poses)


    plt.figure(1)
    plt.subplot(2, len(classifier_results), 1) 

    centre_plot_on_pose(target.pose, 6)

    draw_pose_arrow(target.pose, arrow_length = 0.5)
    
    plt.scatter([p.pose.position.x for p in landmarks], 
                    [p.pose.position.y for p in landmarks],
                    s = 400,
                    c = 'pink', alpha = 0.8)

    plt.scatter(bad_samples[:,0], bad_samples[:,1], c='r', s = 40)
    plt.scatter(good_samples[:,0], good_samples[:,1], c='g', s = 40)
    

    plot_n = len(classifier_results)
    for classifier_result in classifier_results:
        plot_n += 1
        
        # plot classifier relation metrics, e.g. distances or anges
        ax1 = plt.subplot(2, len(classifier_results), plot_n) 
        classifier_metrics = classifier_result[2]
        classifier = classifier_result[3]
        print classifier_metrics[0]
        # if this is a 1d data set, use a histogram
        if len(classifier_metrics[0]) == 1:
            n, bins, patches = ax1.hist(classifier_metrics, 20, normed=1, facecolor='green', alpha=0.5)

            ax2 = ax1.twinx()              

            x_lim = plt.xticks()
        
            x_range = [[x] for x in np.arange(x_lim[0][0], x_lim[0][-1], 0.01)]
        
            probs, resps = classifier.score_samples(x_range)
            ax2.plot(x_range, probs)

            ax2.set_title('rel %s %s: %s' % (classifier_result[0], classifier_result[1].type, classifier_result[4]))
        else:
            ax1.axis((-1.2,1.2,-1.2,1.2))
            ax1.scatter(classifier_metrics[:,0], classifier_metrics[:,1], c='b', s = 40)

            # ax2 = ax1.twinx()              

            # display predicted scores by the model as a contour plot
            x = np.linspace(-1.2, 1.2)
            y = np.linspace(-1.2, 1.2)
            X, Y = np.meshgrid(x, y)
            XX = np.array([X.ravel(), Y.ravel()]).T
            Z = -classifier.score_samples(XX)[0]
            Z = Z.reshape(X.shape)

            CS = ax1.contour(X, Y, Z, norm=LogNorm(vmin=1.0, vmax=1000.0),
                 levels=np.logspace(0, 3, 10))
            # CB = ax1.colorbar(CS, shrink=0.8, extend='both')

            # for mean, covar in zip(classifier.means_, classifier._get_covars()):
            #     print mean
            #     v, w = linalg.eigh(covar)
            #     u = w[0] / linalg.norm(w[0])

            #     print v[0], v[1]

            #     # Plot an ellipse to show the Gaussian component
            #     angle = np.arctan(u[1] / u[0])
            #     angle = 180 * angle / np.pi  # convert to degrees
            #     ell = mpl.patches.Ellipse(mean, v[0], v[1], 180 + angle, color='black')
            #     ell.set_clip_box(ax1.bbox)
            #     ell.set_alpha(0.5)
            #     ax1.add_artist(ell)

            ax1.set_title('rel %s %s: %6.3f' % (classifier_result[0], classifier_result[1].type, classifier_result[4]))

    plt.show()