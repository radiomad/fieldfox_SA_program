import threading

import pyvisa as visa
import os
import time
import csv
import sys
from PyQt5.QtWidgets import *
from PyQt5 import uic, QtCore
import datetime
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

measurement_foldername = 'measurement_data'

class WindowClass(QMainWindow, uic.loadUiType('main.ui')[0]):

    # Parameters
    flag_connected = False
    flag_measurement_running = False

    start_freq = None
    stop_freq = None
    n_points = None

    # resource manager and fieldfox
    rm = None
    myFieldFox = None

    def __init__(self) :
        super().__init__()
        self.init_time = time.time()
        self.setupUi(self)

        self.setWindowTitle("FieldFox SA Measurement Program")

        # resource manager
        self.rm = visa.ResourceManager()

        # load default settings
        self.load_default_settings()

        # crate graph
        self.fig = plt.Figure()
        self.canvas = FigureCanvas(self.fig)
        self.grid.addWidget(self.canvas)
        self.ax = self.fig.add_subplot(1, 1, 1)

        # button signal
        self.btn_connect.clicked.connect(self.connect)
        self.btn_start.clicked.connect(self.start_thread)
        self.btn_start.setEnabled(False)

    def load_default_settings(self):
        self.ed_ip.setText('192.168.0.124')
        self.ed_start_freq.setText('9.9995e9')
        self.ed_stop_freq.setText('10.0005e9')
        self.ed_n_points.setText('401')
        self.ed_n_samples.setText('50')
        self.ed_interval.setText('0.2')

    def connect(self):
        ip_addr = self.ed_ip.text()

        self.log("Trying to connect " + ip_addr)
        try:
            self.myFieldFox = self.rm.open_resource("TCPIP0::" + ip_addr + "::inst0::INSTR")
            self.myFieldFox.timeout = 10000

            self.myFieldFox.write("*CLS")
            self.myFieldFox.write("*IDN?")
            msg = self.myFieldFox.read()

            # Change mode to SA
            self.myFieldFox.write("INST:SEL 'SA'; *OPC?")
            self.myFieldFox.read()

            self.log("Successfully connected")
            self.log("Device: " + msg)
            self.flag_connected = True

        except Exception as e:
            self.log("ERROR: Unable to connect", log_level=1)

        if self.flag_connected:
            self.btn_connect.setText('Connected')
            self.btn_connect.setEnabled(False)
            self.btn_start.setEnabled(True)


    def start_thread(self):
        thread = threading.Thread(target=self.start)
        thread.start()

    def start(self):
        new_start_freq = float(self.ed_start_freq.text())
        new_stop_freq = float(self.ed_stop_freq.text())
        new_n_points = int(self.ed_n_points.text())

        site = self.ed_site.text()
        n_samples = int(self.ed_n_samples.text())
        interval = float(self.ed_interval.text())

        filename = measurement_foldername + '//' + site + '.csv'
        if os.path.exists(filename):
            self.log("ERROR: File for " + site + " already exists", log_level=1)
            return

        if not self.flag_connected:
            self.log("ERROR: Not connected to the device", log_level=1)
            return

        self.btn_start.setEnabled(False)
        self.btn_start.setText('Wait')

        # check if new settings need to be applied
        if self.start_freq != new_start_freq:
            self.myFieldFox.write("SENS:FREQ:STAR " + str(new_start_freq))
            self.myFieldFox.write("SENS:FREQ:STAR?")
            self.start_freq = float(self.myFieldFox.read())
            self.log("Start frequency: " + str(self.start_freq))
            self.start_freq = new_start_freq

        if self.stop_freq != new_stop_freq:
            self.myFieldFox.write("SENS:FREQ:STOP " + str(new_stop_freq))
            self.myFieldFox.write("SENS:FREQ:STOP?")
            self.stop_freq = float(self.myFieldFox.read())
            self.log("Stop frequency: " + str(self.stop_freq))
            self.stop_freq = new_stop_freq

        if self.n_points != new_n_points:
            self.myFieldFox.write("SENS:SWE:POIN " + str(new_n_points))
            self.myFieldFox.write("SENS:SWE:POIN?")
            self.n_points = int(self.myFieldFox.read())
            self.log("# points: " + str(self.n_points))
            self.n_points = new_n_points

        self.log('--Start measurement--')

        # Create file
        f = open(filename, 'w', newline='')
        wr = csv.writer(f)

        # Put file headers
        measurement_init_time = time.time()
        wr.writerow(['Create Date', datetime.datetime.now().strftime("%Y%m%d_%H%M%S")])
        wr.writerow(['Start Freq', str(self.start_freq)])
        wr.writerow(['Stop Freq', str(self.stop_freq)])
        wr.writerow(['# Points', str(self.n_points)])
        wr.writerow(['# Samples', str(n_samples)])
        wr.writerow(['Interval', str(interval)])
        wr.writerow((['Time', str(measurement_init_time)]))

        # Store measurement data
        count = 0
        max_curr_data = []
        while count < n_samples:
            begin_time = time.time()
            self.myFieldFox.write("TRACE:DATA?")
            curr_dat = [float(x) for x in self.myFieldFox.read().split(",")]

            max_curr_data.append(max(curr_dat))
            self.log('%d/%d, max: %.2f dbm'%(count+1, n_samples, max(curr_dat)))

            wr.writerow([begin_time - measurement_init_time] + curr_dat)

            # plot graph
            self.ax.cla()
            df = (self.stop_freq - self.start_freq) / (self.n_points - 1)
            freq = [self.start_freq + i*df for i in range(self.n_points)]

            freq_type = 0       # 0: Hz, 1: kHz, 2: MHz, 3: GHz
            if self.start_freq > 1e9:
                freq_type = 3
                freq = [f / 1e9 for f in freq]
            elif self.start_freq > 1e6:
                freq_type = 2
                freq = [f / 1e6 for f in freq]
            elif self.start_freq > 1e3:
                freq_type = 1
                freq = [f / 1e3 for f in freq]
            else:
                freq_type = 0

            self.ax.plot(freq, curr_dat)
            if freq_type == 3:
                self.ax.set_xlabel('Freq [GHz]')
            elif freq_type == 2:
                self.ax.set_xlabel('Freq [MHz]')
            elif freq_type == 1:
                self.ax.set_xlabel('Freq [kHz]')
            else:
                self.ax.set_xlabel('Freq [Hz]')
            self.ax.set_ylabel('Level [dBm]')
            self.canvas.draw()

            # increment count
            count += 1

            # sleep if needed
            elapsed_time = time.time() - begin_time
            sleep_time = interval - elapsed_time
            if sleep_time > 0:
                time.sleep(sleep_time)

        # close file
        f.close()
        self.log(filename + " created")

        self.btn_start.setEnabled(True)
        self.btn_start.setText('Start')

    def log(self, log_str, log_level=0):
        # add time
        log_str = self.get_elapsed_time() + ' - ' + log_str
        print(log_str)

        # change color if needed
        if log_level > 0:
            log_str = "<span style=color:#ff0000>" + log_str + "</span>"
        self.logbox.append(log_str)
        self.logbox.verticalScrollBar().setValue(self.logbox.verticalScrollBar().maximum())
        time.sleep(0.001)

    def get_elapsed_time(self):
        elapsed_time = time.time() - self.init_time
        h = elapsed_time // 3600
        m = (elapsed_time % 3600) // 60
        s = elapsed_time % 60

        if h > 0:
            return '%d:%02d:%02d' % (h, m, s)
        else:
            return '%02d:%02d' % (m, s)


if __name__ == "__main__" :
    if not os.path.exists(measurement_foldername):
        os.makedirs(measurement_foldername)
    # os.add_dll_directory("C:\\Program Files\\Keysight\\IO Libraries Suite\\bin") # removed for linux compatabilty
    os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'

    # run application
    app = QApplication(sys.argv)
    app.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    myWindow = WindowClass() 
    myWindow.show()
    app.exec_()
