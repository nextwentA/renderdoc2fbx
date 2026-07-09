# -*- coding: utf-8 -*-
"""
progressbar dispaly 
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from PySide2.QtCore import QTimer

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2021-04-17 19:50:02"

from PySide2 import QtWidgets, QtCore, QtGui


class MProgressDialog(QtWidgets.QProgressDialog):
    def __init__(
        self,
        status=u"progress...",
        button_text=u"Cancel",
        minimum=0,
        maximum=100,
        parent=None,
        title="",
    ):
        super(MProgressDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags())
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setWindowTitle(status if title else title)
        self.setMinimumWidth(520)
        bar = QtWidgets.QProgressBar(self)
        bar.setFixedHeight(22)
        bar.setStyleSheet(
            """
            QProgressBar {
                color: white;
                border: 1px solid #2a5a2a;
                border-radius: 6px;
                background: #2b2b2b;
                text-align: center;
                font-weight: bold;
            }

            QProgressBar::chunk {
                background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0    #1a7a1a,
                stop: 0.4  #2db52d,
                stop: 0.5  #28b028,
                stop: 1    #1a7a1a );
                border-radius: 5px;
                border: none;
            }
            """
        )
        bar.setAlignment(QtCore.Qt.AlignCenter)
        self.setBar(bar)
        self.setLabelText(status)
        self.setCancelButtonText(button_text)
        self.setRange(minimum, maximum)
        self.setValue(minimum)
        
        # NOTE show the progressbar without blocking
        self.show()
        QtWidgets.QApplication.processEvents()

    @classmethod
    def loop(cls, seq, **kwargs):
        self = cls(**kwargs)
        if not kwargs.get("maximum"):
            self.setMaximum(len(seq))
        for i, item in enumerate(seq, 1):

            if self.wasCanceled():
                break
            try:
                yield i, item  # with body executes here
            except:
                import traceback

                traceback.print_exc()
                self.deleteLater()
            self.setValue(i)
        self.deleteLater()
