from __future__ import division, print_function
from threading import Thread

import os
import ConfigParser
import logging

import numpy as np
import pandas as pd

from atrial_fibrillation import AtrialFibrillation
from ventricular_tachycardia import VentricularTachycardia
from apc_pvc_helper import APC_helper
from pvc_hamilton import PVC
from respiration_AD import RespiratoryAD
from sleep_AD import SleepAD

__author__ = "Dipankar Niranjan, https://github.com/Ras-al-Ghul"

# Logging config
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)


class AnomalyDetector(object):
    """
    implements methods to call various Anomaly Detection Algorithms
    """

    def __init__(self):
        self.config = ConfigParser.RawConfigParser()
        dirname = os.path.dirname(os.path.realpath(__file__))
        cfg_filename = os.path.join(dirname, 'anomaly_detector.cfg')
        self.config.read(cfg_filename)
        self.window_size =\
            self.config.getint('Atrial Fibrillation', 'window_size')
        self.vt_result = None

    def af_anomaly_detect(self, rr_intervals, hr_quality_indices):
        """
        executes the Atrial Fibrillation Anomaly detection
        Input:
            rr_intervals:           a 2D pandas dataframe -
                                    (refer rrinterval.txt from Hexoskin record)
                                    first column named "hexoskin_timestamps" -
                                    contains 'int' timestamps
                                    second column named as "rr_int" -
                                    contains 'double' interval data
            hr_quality_indices:     a 2D pandas dataframe -
                                    (refer hr_quality.txt from Hexoskin record)
                                    first column named "hexoskin_timestamps" -
                                    containts 'int' timestamps
                                    second column named as "quality_ind" -
                                    contains 'int' quality indices,
                                    with max value 127

        Output:
            returns:
            if anomaly:
                'dict' with follwing keys:
                    start_hexo_timestamp:   an integer denoting timestamp of
                                            the first record
                    end_hexo_timestamp:     an integer denoting timestamp of
                                            32/64/128 - last record
                    num_of_NEC:             a small integer, higher the number,
                                            more severe the anomaly here
                    data_reliability:       a small integer, which denotes as a
                                            percentage, the quality of the data
                                            in this window
                                            the higher the percentage, worse
                                            the quality
                    window_size:            a small integer, takes 32/64/128
                                            as values
            else:
                None

        Notes:
            based on 'A Simple Method to Detect
            Atrial Fibrillation Using RR Intervals'
            by Jie Lian et. al.
            Note the return value (if not 'None') and
            check with the data_reliability and previous
            data timestamps to set AFAlarmAttribute at
            the health_monitor server
        """

        if not (len(rr_intervals)) == self.window_size:
            raise ValueError("window length of rr_intervals\
                passed doesn't match config file")

        if not (rr_intervals['hexoskin_timestamps'][0] >=
                hr_quality_indices['hexoskin_timestamps'][0] and
                rr_intervals['hexoskin_timestamps'][len(rr_intervals)-1] <=
                hr_quality_indices
                ['hexoskin_timestamps'][len(hr_quality_indices)-1]):
                pass
                # raise ValueError("first rr_interval timestamp\
                #  and last rr_interval timestamp must lie within first \
                #  and last timestamp of hr_quality")

        AF = AtrialFibrillation(rr_intervals, hr_quality_indices,
                                self.config)
        return AF.get_anomaly()

    def vt_anomaly_detect(self, ecg, rr_intervals,
                          rr_interval_status, prev_ampl):
        """
        creates an object and calls the Ventricular Tachycardia
        anomaly detection methods
        Input:
            ecg:                    a 2D pandas dataframe -
                                    (refer ecg.txt from Hexoskin record)
                                    first column named "hexoskin_timestamps" -
                                    contains 'int' timestamps
                                    second column named as "ecg_val" -
                                    contains 'int' raw ecg data
            rr_intervals:           a 2D pandas dataframe -
                                    (refer rrinterval.txt from Hexoskin record)
                                    first column named "hexoskin_timestamps" -
                                    contains 'int' timestamps
                                    second column named as "rr_int" -
                                    contains 'double' interval data
            rr_intervals_status:    a 2D pandas dataframe -
                                    (refer rrintervalstatus from Hexoskin API)
                                    first column named "hexoskin_timestamps" -
                                    containts 'int' timestamps
                                    second column named as "rr_status" -
                                    contains 'int' quality indices.

        Output:
            sets:
            vt_result:  this is an attribute of an object of this
                        (Anomaly Detector) class. Its value can
                        be read from the caller method. Its value
                        is set to __zero_one_count which is
                        described next.

            __zero_one_count    -   if it is the string True, it means
                                    that analysis of next 6 seconds is
                                    required
                                -   if it is False, it means that next 6
                                    second analysis is not required
                                -   if it has an integer value then it
                                    means that a VT event has been detected
                                    and it has to be stored in the anomaly
                                    database and of course next 6 second
                                    analysis is required

        Notes:
            based on the following three papers:

            'Ventricular Tachycardia/Fibrillation Detection
            Algorithm for 24/7 Personal Wireless Heart Monitoring'
            by Fokkenrood et. al.

            'Real Time detection of ventricular fibrillation
            and tachycardia' by Jekova et. al.

            'Increase in Heart Rate Precedes Episodes of
            Ventricular Tachycardia and Ventricular
            Fibrillation in Patients with Implantahle
            Cardioverter Defihrillators: Analysis of
            Spontaneous Ventricular Tachycardia Database'
            by Nemec et. al.

            Refer to readme for more details
        """
        __zero_one_count = True

        VTobj = VentricularTachycardia(ecg, rr_intervals,
                                       rr_interval_status, self.config)

        further_analyze = VTobj.analyze_six_second()
        # if initial analysis indicates that further analysis
        # is not required
        if not further_analyze:
            __zero_one_count = False
            self.vt_result = __zero_one_count

        logging.info("Doing further analysis")

        # perform the preprocessing
        VTobj.signal_preprocess()

        # call the DangerousHeartActivity detector
        cur_ampl, stop_cur = VTobj.DHA_detect(prev_ampl)

        # whatever be the results of the following stages,
        # we necessarily have to analyze the next six second epoch

        # if further analysis is not required
        if stop_cur is True:
            self.vt_result = __zero_one_count

        # asystole detector
        vtvfres = VTobj.asystole_detector(cur_ampl)

        # to analyze next six second epoch
        if vtvfres == 'VT/VF':
            # A VT episode has been found
            logging.info("%s" % str(vtvfres))
            __zero_one_count = VTobj.zero_one_count
            self.vt_result = __zero_one_count
        else:
            # not a VT episode
            logging.info("%s" % str(vtvfres))
            self.vt_result = __zero_one_count

    def apc_pvc(self, init_timestamp):
        """
        this is only for testing and reference purpose,
        in actuality, create APC_helper object and call
        directly - no need to create AD object for this
        Input:
            timestamp:  the first timestamp

        Output:
            stores to the results dict of the APC class

        Notes:
            based on the following paper:

            'Automatic detection of premature atrial
            contractions in the electrocardiogram'
            by Krasteva et. al.

            Refer to readme for more details
        """
        apcHelperObj = APC_helper()
        apcHelperObj.populate_DS()
        apcHelperObj.popluate_aux_structures(init_timestamp)

        apcHelperObj.apcObj.absolute_arrhythmia()

    def pvc_Hamilton(self, init_timestamp):
        """
        this is only for testing and reference purpose,
        in actuality, create PVC object and call
        directly - no need to create AD object for this
        Input:
            timestamp:  the first timestamp

        Output:
            stores to the results dict of the PVC class

        Notes:
            based on:

            'Open Source ECG Analysis Software
            Documentation'
            by Patrick S. Hamilton

            Refer to readme for more details
        """
        pvcObj = PVC()
        pvcObj.populate_data()
        pvcObj.beat_classf_analyzer(init_timestamp)

    def resp_AD(self, init_timestamp):
        """
        this is only for testing and reference purpose,
        in actuality, create RespiratoryAD object and call
        directly - no need to create AD object for this
        Input:
            timestamp:  the first timestamp

        Output:
            stores to the results dict of the RespiratoryAD class

        Notes:
            based on:

            'http://wps.prenhall.com/wps/media/objects\
            /2791/2858109/toolbox/Box15_1.pdf'

            Refer to readme for more details
        """
        respObj = RespiratoryAD(self.config, init_timestamp)
        th1 = Thread(target=respObj.populate_DS, args=[])
        th1.start()
        th1.join()

        th2 = Thread(target=respObj.tidal_volume_anomaly, args=[])
        th2.start()

        th3 = Thread(target=respObj.minute_ventilation_anomaly, args=[])
        th3.start()

        th4 = Thread(target=respObj.resp_variation, args=[])
        th4.start()

        th5 = Thread(target=respObj.resp_classf, args=[])
        th5.start()

        th6 = Thread(target=respObj.delete_DS, args=[])
        th6.start()

    def sleep_AD(self):
        """
        this is only for testing and reference purpose,
        in actuality, create SleepAD object and call
        directly - no need to create AD object for this
        Input:
            None

        Output:
            stores to the anomaly_dict of the SleepAD class

        Notes:
            based on:

            'https://www.sleepcycle.com/how-it-works/'
            'http://blog.doctoroz.com/oz-experts/calculating-your-
            perfect-bedtime-and-sleep-efficiency'
            'https://api.hexoskin.com/docs/resource/sleepphase/'
            'https://api.hexoskin.com/docs/resource/sleepposition/''
            'https://api.hexoskin.com/docs/resource/metric/'

            Refer to readme for more details
        """
        SleepObj = SleepAD()
        SleepObj.populate_DS()
        SleepObj.get_metrics()
        SleepObj.calc_woke_up_count()
        SleepObj.get_possible_anomaly()


def main():
    AD = AnomalyDetector()
    rr_intervals = (pd.read_csv('rrinterval.txt',
                    sep="\t",
                    nrows=AD.config.getint('Atrial Fibrillation',
                                           'window_size'),
                    dtype={"hexoskin_timestamps": np.int64,
                           "rr_int": np.float64},
                    header=None,
                    names=["hexoskin_timestamps", "rr_int"]))
    hr_quality_indices = (pd.read_csv('hr_quality.txt',
                                      sep="\t",
                                      nrows=AD.config.
                                      getint('Atrial Fibrillation',
                                             'window_size')-8,
                                      dtype={"hexoskin_timestamps": np.int64,
                                             "quality_ind": np.int32},
                                      header=None,
                                      names=["hexoskin_timestamps",
                                             "quality_ind"]))
    # call the Atrial Fibrillation anomaly detection method
    logging.info("%s" %
                 str(AD.af_anomaly_detect(rr_intervals, hr_quality_indices)))

    ecg = (pd.read_csv('ecg.txt',
                       sep="\t",
                       nrows=256*6,
                       dtype={"hexoskin_timestamps": np.int64,
                              "ecg_val": np.int32},
                       header=None,
                       names=["hexoskin_timestamps", "ecg_val"]))
    """
    for testing, ensure that only the relevant timestamped
    rr_intervals are present in rrinterval.txt as it reads
    a preset 7 rows
    """
    rr_intervals = (pd.read_csv('rrinterval.txt',
                                sep="\t",
                                nrows=7,
                                dtype={"hexoskin_timestamps": np.int64,
                                       "rr_int": np.float64},
                                header=None,
                                names=["hexoskin_timestamps", "rr_int"]))
    """
    for testing, ensure that only the relevant timestamped
    rr_status are present in rr_interval_status.txt as it
    reads a preset 7 rows
    """
    rr_interval_status = (pd.read_csv('rr_interval_status.txt',
                                      sep="\t",
                                      nrows=7,
                                      dtype={"hexoskin_timestamps": np.int64,
                                             "rr_status": np.int32},
                                      header=None,
                                      names=["hexoskin_timestamps",
                                             "rr_status"]))
    # call the Ventricular Tachycardia anomaly detection method
    AD.vt_anomaly_detect(ecg, rr_intervals, rr_interval_status, 1400)

    AD.apc_pvc(383021266184)

    AD.pvc_Hamilton(383021266184)

    AD.resp_AD(383021140185)

    AD.sleep_AD()


if __name__ == '__main__':
    main()
