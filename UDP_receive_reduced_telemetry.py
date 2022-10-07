
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
parser.add_argument('-ppf','--ppf', type=int, default=5000) #packets per file
parser.add_argument('-n_cal','--ncal', type=int, default=100) #number of packets for calibration 
parser.add_argument('-tl','--tl',type=float,default=1.2) #local save threshold [2.45 LOCAL]
parser.add_argument('-tt','--tt',type=float,default=1.5) #transmit save threshold [3.0 TRANSMIT]
parser.add_argument('-slp','--slp',type=int,default=120) #sleep time initial
parser.add_argument('-mode','--mode',default='mmm') #mode for decision making on whether file is interesting. Default is 'mmm' (ie max minus min) 
parser.add_argument('-tmout','--tmout',type=int,default=180)
parser.add_argument('-rdfctr','--rdfctr',type=int,default=100) #sets n for nth elements used for max/min calculations 
parser.add_argument('-master','--master',nargs="+", type=int, default=[7]) # sets channel that should be treated as master in calibration
parser.add_argument('-drop','--drop',nargs="+", type=int, default=[6,4,3,2,1]) #drop channels [6, 3, 2] 

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
n = 0

local_factor = args.tl
transmit_factor = args.tt
rdfctr = args.rdfctr

calibrated_threshold = 0
data_threshold = 0

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

# Default for ppf is 5000. 10.5 seconds of data with each file @ 5000 * 1250 bytes = 6.25megabytes
packets_per_file = args.ppf

packets_for_calibration = args.ncal #num packets to calibrate over
calibration_array_mean = np.zeros(packets_for_calibration)
calibration_array_mmm = np.zeros(packets_for_calibration)

#############


###########################################################
#Calibration routine
###########################################################
def calibrate():
	global calibrated_threshold
	print("Calibrating......")
	try:
		for i in range(packets_for_calibration):
			reduced_data = bytearray(b'')
			data, addr = sock.recvfrom(1250)
			if(len(data) == 1248):
				data = data[0::2] #remove ground sampling
				if(args.master):
					print("Assigning master channel(s). Init Len: " + str(len(data)))
					for chan in args.master:
						reduced_data = reduced_data + data[chan::8]
					data = reduced_data
					print("Final Len:" + str(len(data)))
				calibration_array_mean[i] = statistics.mean(data)
				calibration_array_mmm[i] = max(data) - min(data)
		calibrated_threshold_mean = statistics.mean(calibration_array_mean)
		calibrated_threshold_mmm = statistics.mean(calibration_array_mmm)

		#UNCOMMENT BELOW TO ACTUALLY SEE CALIBRATION ARRAY
		#print([x for x in data])

		print("Calibrated MEAN:" + str(calibrated_threshold_mean))
		print("Calibrated MAX-MIN:" + str(calibrated_threshold_mmm))

	except socket.timeout:
		print("socket timed out during calibration")
		file=open("./error/timeout.txt","w")
		file.write('T')
		file.close()
		quit()

	#SETS APPROPRIATE CALIBRATION THRESHOLD BASED ON MODE
	if(args.mode == 'mmm'):
		calibrated_threshold = calibrated_threshold_mmm
	elif(args.mode == 'mean'):
		calibrated_threshold = calibrated_threshold_mean
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
			collected_tru_data_check = collected_tru_data

			remaining_channels = 8
			if(args.drop):
				print("Dropping channel(s):" + str(args.drop))
				for chan in args.drop:
					del collected_tru_data_check[chan-1::remaining_channels]
					remaining_channels -= 1

			collected_tru_data_check = collected_tru_data[::rdfctr] #for time saving, reduce array size
			if(args.mode == 'mmm'):
				data_threshold = max(collected_tru_data_check) - min(collected_tru_data_check)
			elif(args.mode == 'mean'):
				data_threshold = max(collected_tru_data_check)

			print("Threshold for this file: " + str("{:.3f}".format(data_threshold)))
			print("Threshold to exceed for saving locally: " + str("{:.3f}".format(local_factor * calibrated_threshold)))
			print("Threshold to exceed for transmitting: " + str("{:.3f}".format(transmit_factor * calibrated_threshold)))

			if data_threshold > (transmit_factor * calibrated_threshold):
				savedata_transmit(collected_tru_data)
			elif data_threshold > (local_factor * calibrated_threshold):
				savedata_local(collected_tru_data)
			else:
				print("DISCARDING DATA")
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


