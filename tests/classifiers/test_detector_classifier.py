# MIT License
#
# Copyright (C) IBM Corporation 2018
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import unittest

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from art.classifiers import PyTorchClassifier, DetectorClassifier
from art.utils import get_labels_np_array, load_mnist, master_seed

logger = logging.getLogger('testLogger')

NB_TRAIN = 10
NB_TEST = 2


class Model(nn.Module):
    def __init__(self):
        super(Model, self).__init__()
        self.conv = nn.Conv2d(1, 16, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc = nn.Linear(2304, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv(x)))
        x = x.view(-1, 2304)
        logit_output = self.fc(x)

        return logit_output


class Flatten(nn.Module):
    def forward(self, x):
        n, _, _, _ = x.size()
        result = x.view(n, -1)

        return result


class TestDetectorClassifier(unittest.TestCase):
    """
    This class tests the functionalities of the DetectorClassifier.
    """

    @classmethod
    def setUpClass(cls):
        # Get MNIST
        (x_train, y_train), (x_test, y_test), _, _ = load_mnist()
        x_train, y_train = x_train[:NB_TRAIN], y_train[:NB_TRAIN]
        x_test, y_test = x_test[:NB_TEST], y_test[:NB_TEST]
        x_train = np.swapaxes(x_train, 1, 3)
        x_test = np.swapaxes(x_test, 1, 3)
        cls.mnist = (x_train, y_train), (x_test, y_test)

        # Define the internal classifier
        model = Model()
        loss_fn = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.01)
        classifier = PyTorchClassifier(model=model, loss=loss_fn, optimizer=optimizer, input_shape=(1, 28, 28),
                                       nb_classes=10, clip_values=(0, 1))
        classifier.fit(x_train, y_train, batch_size=100, nb_epochs=2)

        # Define the internal detector
        conv = nn.Conv2d(1, 16, 5)
        linear = nn.Linear(2304, 1)
        torch.nn.init.xavier_uniform_(conv.weight)
        torch.nn.init.xavier_uniform_(linear.weight)
        model = nn.Sequential(conv, nn.ReLU(), nn.MaxPool2d(2, 2), Flatten(), linear)
        loss_fn = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.01)
        detector = PyTorchClassifier(model=model, loss=loss_fn, optimizer=optimizer, input_shape=(1, 28, 28),
                                     nb_classes=1, clip_values=(0, 1))

        # Define the detector-classifier
        cls.detector_classifier = DetectorClassifier(classifier=classifier, detector=detector)

    def setUp(self):
        # Set master seed
        master_seed(1234)

    def test_predict(self):
        # Get MNIST
        (_, _), (x_test, _) = self.mnist

        # Test predict
        preds = self.detector_classifier.predict(x=x_test)
        self.assertTrue(np.array(preds.shape == (NB_TEST, 11)).all())
        self.assertAlmostEqual(float(np.sum(get_labels_np_array(preds))), NB_TEST)

    def test_nb_classes(self):
        dc = self.detector_classifier
        self.assertEqual(dc.nb_classes(), 11)

    def test_input_shape(self):
        dc = self.detector_classifier
        self.assertTrue(np.array(dc.input_shape == (1, 28, 28)).all())

    def _derivative(self, x, i1, i2, i3, i4):
        delta = 1e-5
        x_minus = x.copy()
        x_minus[:, i2, i3, i4] -= delta
        x_plus = x.copy()
        x_plus[:, i2, i3, i4] += delta

        result_plus = self.detector_classifier.predict(x_plus)
        result_minus = self.detector_classifier.predict(x_minus)
        result = (result_plus[:, i1] - result_minus[:, i1]) / (2 * delta)

        return result

    def test_class_gradient1(self):
        # Get MNIST
        (_, _), (x_test, _) = self.mnist

        # Get the classifier
        dc = self.detector_classifier

        # Test label = None
        grads = dc.class_gradient(x=x_test, label=None)

        self.assertTrue(np.array(grads.shape == (NB_TEST, 11, 1, 28, 28)).all())
        self.assertNotEqual(np.sum(grads), 0)

        # Sanity check
        for i1 in range(grads.shape[1]):
            for i2 in range(grads.shape[2]):
                for i3 in range(grads.shape[3]):
                    for i4 in range(grads.shape[4]):
                        result = self._derivative(x_test, i1, i2, i3, i4)

                        for i in range(grads.shape[0]):
                            if np.abs(result[i]) > 0.5:
                                # print(result[i], grads[i, i1, i2, i3, i4])
                                self.assertEqual(np.sign(result[i]), np.sign(grads[i, i1, i2, i3, i4]))

    def test_class_gradient2(self):
        # Get MNIST
        (_, _), (x_test, _) = self.mnist

        # Get the classifier
        dc = self.detector_classifier

        # Test label = 5
        grads = dc.class_gradient(x=x_test, label=5)

        self.assertTrue(np.array(grads.shape == (NB_TEST, 1, 1, 28, 28)).all())
        self.assertNotEqual(np.sum(grads), 0)

        # Sanity check
        for i2 in range(grads.shape[2]):
            for i3 in range(grads.shape[3]):
                for i4 in range(grads.shape[4]):
                    result = self._derivative(x_test, 5, i2, i3, i4)

                    for i in range(grads.shape[0]):
                        if np.abs(result[i]) > 0.5:
                            # print(result[i], grads[i, 0, i2, i3, i4])
                            self.assertEqual(np.sign(result[i]), np.sign(grads[i, 0, i2, i3, i4]))

    def test_class_gradient3(self):
        # Get MNIST
        (_, _), (x_test, _) = self.mnist

        # Get the classifier
        dc = self.detector_classifier

        # Test label = 10
        grads = dc.class_gradient(x=x_test, label=10)

        self.assertTrue(np.array(grads.shape == (NB_TEST, 1, 1, 28, 28)).all())
        self.assertNotEqual(np.sum(grads), 0)

        # Sanity check
        for i2 in range(grads.shape[2]):
            for i3 in range(grads.shape[3]):
                for i4 in range(grads.shape[4]):
                    result = self._derivative(x_test, 10, i2, i3, i4)

                    for i in range(grads.shape[0]):
                        if np.abs(result[i]) > 0.5:
                            # print(result[i], grads[i, 0, i2, i3, i4])
                            self.assertEqual(np.sign(result[i]), np.sign(grads[i, 0, i2, i3, i4]))

    def test_class_gradient4(self):
        # Get MNIST
        (_, _), (x_test, _) = self.mnist

        # Get the classifier
        dc = self.detector_classifier

        # Test label = array
        label = np.array([2, 10])
        grads = dc.class_gradient(x=x_test, label=label)

        self.assertTrue(np.array(grads.shape == (NB_TEST, 1, 1, 28, 28)).all())
        self.assertNotEqual(np.sum(grads), 0)

        # Sanity check
        for i2 in range(grads.shape[2]):
            for i3 in range(grads.shape[3]):
                for i4 in range(grads.shape[4]):
                    result1 = self._derivative(np.array([x_test[0]]), 2, i2, i3, i4)
                    result2 = self._derivative(np.array([x_test[1]]), 10, i2, i3, i4)

                    if np.abs(result1[0]) > 0.5:
                        # print(result1[0], grads[0, 0, i2, i3, i4])
                        self.assertEqual(np.sign(result1[0]), np.sign(grads[0, 0, i2, i3, i4]))

                    if np.abs(result2[0]) > 0.5:
                        # print(result2[0], grads[1, 0, i2, i3, i4])
                        self.assertEqual(np.sign(result2[0]), np.sign(grads[1, 0, i2, i3, i4]))

    def test_set_learning(self):
        dc = self.detector_classifier

        self.assertTrue(dc.classifier._model.training)
        self.assertTrue(dc.detector._model.training)
        self.assertIs(dc.learning_phase, None)

        dc.set_learning_phase(False)
        self.assertFalse(dc.classifier._model.training)
        self.assertFalse(dc.detector._model.training)
        self.assertFalse(dc.learning_phase)

        dc.set_learning_phase(True)
        self.assertTrue(dc.classifier._model.training)
        self.assertTrue(dc.detector._model.training)
        self.assertTrue(dc.learning_phase)

    def test_save(self):
        model = self.detector_classifier
        import tempfile
        import os
        t_file = tempfile.NamedTemporaryFile()
        full_path = t_file.name
        t_file.close()
        base_name = os.path.basename(full_path)
        dir_name = os.path.dirname(full_path)
        model.save(base_name, path=dir_name)

        self.assertTrue(os.path.exists(full_path + "_classifier.optimizer"))
        self.assertTrue(os.path.exists(full_path + "_classifier.model"))
        os.remove(full_path + '_classifier.optimizer')
        os.remove(full_path + '_classifier.model')

        self.assertTrue(os.path.exists(full_path + "_detector.optimizer"))
        self.assertTrue(os.path.exists(full_path + "_detector.model"))
        os.remove(full_path + '_detector.optimizer')
        os.remove(full_path + '_detector.model')

    def test_repr(self):
        repr_ = repr(self.detector_classifier)
        self.assertIn('art.classifiers.detector_classifier.DetectorClassifier', repr_)
        self.assertIn('preprocessing=(0, 1)', repr_)


if __name__ == '__main__':
    unittest.main()
