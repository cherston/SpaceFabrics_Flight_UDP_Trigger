
import socket
import os
import numpy as np
import shutil
import glob
import statistics
import re
from time import sleep
import time
import argparse

UDP_IP = "10.0.10.1"
UDP_PORT = 2004

##########################################################################
#COMMANDLINE ARGUMENT PARSING
##########################################################################

parser  = argparse.ArgumentParser('UDP_receive')
parser.add_argument('-ppf','--ppf', type=int, default=2500) #packets per file [originally 5000]
parser.add_argument('-n_cal','--ncal', type=int, default=100) #number of packets for calibration 
parser.add_argument('-tl','--tl',type=float,default=1.3) #local save threshold
parser.add_argument('-tt','--tt',type=float,default=1.5) #transmit save threshold
parser.add_argument('-slp','--slp',type=int,default=120) #sleep time initial
parser.add_argument('-mode','--mode',default='mmm') #mode for decision making on whether file is interesting. Default is 'mmm' (ie max minus min) 
parser.add_argument('-tmout','--tmout',type=int,default=180) #timeout after poweron to allow time for payload bootup 
parser.add_argument('-rdfctr','--rdfctr',type=int,default=100) #sets n for nth elements used for max/min calculations 
parser.add_argument('-master','--master',nargs="+", type=int, default=[]) # sets channel that should be treated as master in calibration
parser.add_argument('-drop','--drop',nargs="+", type=int, default=[]) #drop channels.l
parser.add_argument('-filtchan','--filtchan',nargs="+", type=int, default=[]) #drop channels.l

args = parser.parse_args()

##########################################################################
#END COMMANDLINE ARGUMENTS
##########################################################################

##############
#SET UP SOCKET
#############
sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM) # UDP
sock.bind((UDP_IP,UDP_PORT))
sock.settimeout(args.tmout)
#############


#############
#VARIABLE DECLARATION
#############

fs = 480*1248  / 8 / 2      #480 packets per second, 1248 bytes per packet, divided by 8 bc 8 channels, divided by 2 bc half discarded for ground sampling
cutoff = 4000  # desired cutoff frequency of the filter, Hz

n = 0

local_factor = args.tl
transmit_factor = args.tt
rdfctr = args.rdfctr
drop = args.drop 
filtchan = args.filtchan


calibrated_threshold = np.zeros(8)
data_threshold = np.zeros(8)

collected = bytearray()

a = glob.glob("./transmit_data/fdata*.txt")
if(a):
	transmit_filenum = int(max([re.findall(r'\d+',k)[0] for k in a])) + 1
else:
	transmit_filenum = 0
print("(note: next available transmit filenum is detected as: " + str(transmit_filenum))

a = glob.glob("./local_data/fdata*.txt")
if(a):
	local_filenum = int(max([re.findall(r'\d+',k)[0] for k in a])) + 1
else:
	local_filenum = 0

slowcontrol_filenum = 0
slowcontrol_counter = 13  
slowcontrol_savenum = 36 * 13 # 10min * slowcontrol_savenum = frequency slow control data is saved. 13 slow control files per acquisition
slow_control_flag = False

packets_per_file = args.ppf

packets_for_calibration = args.ncal #num packets to calibrate over
calibration_array_mean = np.zeros(packets_for_calibration)
calibration_array_mmm = np.zeros(packets_for_calibration)
calibration_mmms = np.zeros(8 - len(drop))
calibration_means = np.zeros(8 - len(drop))

#############


###########################################################
#Calibration routine
###########################################################
def calibrate():
	global calibrated_threshold
	global calibration_means
	global calibration_mmms
	print("Calibrating......")
	try:
		for j in range(8 - len(drop)): #Note that in this design, a separate set of packets are used to calibrate each of 8 channels
			for i in range(packets_for_calibration):
				reduced_data = bytearray(b'')
				data, addr = sock.recvfrom(1250)
				if(len(data) == 1248):
					data = data[0::2] #remove ground sampling
					remaining_channels = 8
					if(drop):
						print("Dropping channel(s):" + str(drop))
						for chan in drop:
							del data[chan-1::remaining_channels]
							remaining_channels -= 1

					
					if(j in filtchan):
						filtered_data = high_pass_filter(np.array(data[j::remaining_channels]),cutoff,fs)
					else: 
						filtered_data = np.array(data[j::remaining_channels])

					calibration_array_mean[i] = statistics.mean(filtered_data) #every 8th element offset by j
					calibration_array_mmm[i] = max(filtered_data) - min(filtered_data) #every 8th element offset by j



					# INSERT: NEED CALIBRATION ROUTINE TO REMOVE DROPPED CHANNELS!!!!!! 

			calibration_means[j] = statistics.mean(calibration_array_mean)
			calibration_mmms[j] = statistics.mean(calibration_array_mmm)

			file = open("./transmit_data/calibration.txt","wb")
			np.savetxt(file,calibration_array_mmm)
			file.close()

			file = open("./transmit_data/settings.txt","wb")
			np.savetxt(file,calibration_array_mmm)
			file.close()

			file = open("./settings_test.txt","wb")
			np.savetxt(file,[local_factor,transmit_factor] + c)
			file.close()
			 
 
			 
			#UNCOMMENT BELOW TO DISPLAY CALIBRATION ARRAY
			#print([x for x in data])

			print("Calibrated MEANS:" + str(calibration_means))
			print("Calibrated MAX-MINS"+ str(calibration_mmms))

	except socket.timeout:
		print("socket timed out during calibration")
		file=open("./error/timeout.txt","w")
		file.write('T')
		file.close()
		quit()

	#SETS APPROPRIATE CALIBRATION THRESHOLD BASED ON MODE
	if(args.mode == 'mmm'):
		calibrated_threshold = calibration_means
	elif(args.mode == 'mean'):
		calibrated_threshold = calibration_mmms


##########################################################
#File save operations
##########################################################
def savedata_local(l_data):
	global local_filenum
	print("LOCAL SAVE")
	file = open("./local_data/fdata_"+str(local_filenum)+".txt","wb")
	file.write(l_data)
	file.close()
	local_filenum +=1

	#remove_data_check()


def savedata_transmit(t_data):
	global transmit_filenum
	print("TRANSMIT SAVE. Filenum: " + str(transmit_filenum))
	tic = time.perf_counter()
	file = open("./transmit_data/fdata_" + str(transmit_filenum) + ".txt","wb")
	file.write(t_data)
	file.close()
	toc = time.perf_counter()
	print("(transmit save down time:" + str("{:.2f}".format(toc-tic)) + " seconds)")
	transmit_filenum +=1

	#remove_data_check()

def savedata_slowcontrol(s_data):
	global slowcontrol_filenum
	global slowcontrol_counter
	global slowcontrol_savenum
	print("SLOW CONTROL SAVE")
	
	if(slowcontrol_counter == 0):
		slowcontrol_counter = slowcontrol_savenum
        #print("skip.." + str(slowcontrol_counter))

	elif(slowcontrol_counter <= 13): # when slowcontrol_savenum = 36, saves every 6 hours (data every 10min, 36 * 10min = 6hrs)
		file = open("./transmit_data/slowcontrol_" + str(slowcontrol_filenum) + ".txt","wb")
		file.write(s_data)
		file.close()

		slowcontrol_filenum -= 1
		sleep(20) # this 20 second sleep is a hack to ensure that telemetry motor data is skipped

		slowcontrol_counter -= 1


#############################################################
#Check for data overage
#############################################################

def remove_data_check():
	total, used, free = shutil.disk_usage("/")
	if(used/total > 0.85): 
		print("removing files due to memory overage")
		if(glob.glob("./local_data/*.txt")):
			os.remove(glob.glob("local_data/*.txt")[0])
		elif(glob.glob("./transmit_data/*.txt")):
			os.remove(glob.glob("transmit_data/*.txt")[0])

#############################################################
#HELPERS: low pass and high pass filtering 
#############################################################

def low_pass_filter(data, band_limit, sampling_rate):
    cutoff_index = int(band_limit * data.size / sampling_rate)
    F = np.fft.fft(data)
    F[cutoff_index + 1 : -cutoff_index] = 0
    return np.fft.ifft(F).real

def high_pass_filter(data, band_limit, sampling_rate):
    cutoff_index = int(band_limit * data.size / sampling_rate)
    F = np.fft.fft(data)
    F[:cutoff_index] = 0
    F[-cutoff_index + 1:] = 0
    return np.fft.ifft(F).real


##########################################################
#Computation & main loop
##########################################################

def max_minus_min(data_packets):
	print("calculating max minus min")
	return fortran_code.minmax1(data_packets)

print("UDP will be initialized after configured sleep time of: " + str(args.slp) + " second(s)")
sleep(args.slp)
calibrate()

print("Calibrated.")
while(True):
	try:
		data, addr = sock.recvfrom(1250) # buffer size is 1250 bytes
		if len(data) == 1248: # checks if this is a standard buffer
			collected+=data
			n+=1
		else:
			savedata_slowcontrol(data)


		if (n > packets_per_file):
			print('********************************************************************')
			print("****Buffer filled to correct size. Determining whether to save****")

			tic = time.perf_counter()

			collected_tru_data = collected[::2] #skip ground reads (which were added for decoupling channels)
			collected_tru_data_check = collected_tru_data[:]

			remaining_channels = 8
			if(drop):
				print("Dropping channel(s):" + str(drop))
				for chan in drop:
					del collected_tru_data_check[chan-1::remaining_channels]
					remaining_channels -= 1

			for k in range(remaining_channels):

				if(k in filtchan):
					collected_tru_data_filt = high_pass_filter(np.array(collected_tru_data_check[k::remaining_channels]),cutoff,fs) # apply filter to kth elements corresponding to channel k 
				else:
					collected_tru_data_filt = collected_tru_data_check[k::remaining_channels]


				collected_tru_data_check_reduced = collected_tru_data_filt[::rdfctr] #for time saving, reduce array size
				if(args.mode == 'mmm'):
					data_threshold[k] = max(collected_tru_data_check_reduced) - min(collected_tru_data_check_reduced)
				elif(args.mode == 'mean'):
					data_threshold[k] = max(collected_tru_data_check_reduced)

				print("Threshold for channel: " + str(k) + ": " + str("{:.3f}".format(data_threshold[k])))
				print("Threshold to exceed for saving locally: " + str("{:.3f}".format(local_factor * calibrated_threshold[k])))
				print("Threshold to exceed for transmitting: " + str("{:.3f}".format(transmit_factor * calibrated_threshold[k])))


				if data_threshold[k] > (transmit_factor * calibrated_threshold[k]):
					savedata_transmit(collected_tru_data)
					break; 
				elif data_threshold[k] > (local_factor * calibrated_threshold[k]):
					savedata_local(collected_tru_data)
					break; 

			#reset byte array and n
			collected = bytearray()
			n=0
			#toc = time.perf_counter()
			toc = time.perf_counter()
			print("(down time during execution:" + str("{:.3f}".format(toc-tic)) + " seconds)")

	except socket.timeout:
		print("socket timed out")

		#write T to a file, which triggers MISSE computer to power cycle
		file=open("./error/timeout.txt","w")
		file.write("T")
		file.close()


