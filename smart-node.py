# load the module
import socket
import tp4000zc
import time
import sys
import os
import traceback
import threading
import signal
import subprocess
sys.path.insert(1, os.path.join(sys.path[0], '../..'))
from util import *

if len(sys.argv) != 13:
	print "Command: python smart-node.py <DMS IP> <DMS PORT> <MY ID> <batteryCapacity> <POWER USB port 1> <LOADTYPE:AMPERES port 1> <POWER USB port 2> <LOADTYPE:AMPERES port 2> <upstream/coordinated> <arrivalTime> <deadline> <scenario>"
	sys.exit(0)


DMSIP = sys.argv[1]
DMSPort = int(sys.argv[2])
myID = int(sys.argv[3])
batteryCapacity = float(sys.argv[4]) # We only use a subset of the battery
powerUSBPort1 = int(sys.argv[5])
load1 = sys.argv[6].split(":")
powerUSBPort2 = int(sys.argv[7])
load2 = sys.argv[8].split(":")
measurementType = sys.argv[9]
arrivalTime = int(sys.argv[10])
deadline = int(sys.argv[11])
scenario = sys.argv[12]

batteryAmpsCharged = 0.0
previousMeasuredCurrent = 0.0
previousMeasuredVoltage = 0.0
shouldRefreshReaders = False
baseLoadToSubstract = {1: 0, 2: 0, 3: 0.034, 4: 0, 6: 0, 7: 0.036, 8: 0.030, 9: 0.031, 10: 0.0, 11: 0.031, 12: 0}

baseLoad = {1: [],
	2: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96],
	3: [],
	4: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96],
	5: [],
	6: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96],
	7: [],
	8: [],
	9: [],
	10: [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 85, 86, 87, 88],
	11: [],
	12: [21, 22, 23, 24, 25, 26, 27, 28]}

loadType1 = load1[0]
loadValue1 = float(load1[1])
loadType2 = load2[0]
loadValue2 = float(load2[1])

CMD_CNTRL_LOAD = "sudo /home/pi/smart-grid-lab/smart-node/powerusb/a.out"
LOG_MEASUREMENTS = True
BUFFER_SIZE = 10024

dtArrival = None
dtDeadline = None

EVArrived = False


expectedUSBPorts = []

if myID in [1]:
	expectedUSBPorts = [0, 1]
elif myID in [2, 3, 4, 6, 7, 8, 9, 10, 11, 12]:
	expectedUSBPorts = [0, 1, 2, 3]
else:
	raise Exception("Wrong node ID !")

loadStates = {}
loadStates[1] = "off"
loadStates[2] = "off"


emptyMeasurements()
emptyEvents()
emptyErrors()
signal.signal(signal.SIGINT, signal_handler)

dmsSock = None

dmsSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
dmsSock.connect((DMSIP, DMSPort))

initLines = "INIT\n"
initLines += "ID=" + str(myID) + "\n"
initLines += "ENDINIT\n"

dmsSock.send(initLines)

def readMulti(dmm):
	# read a value
	val = dmm.read()

	val.numericVal, val.text

	value = abs(float(val.numericVal))

	if "Amps AC" in val.text and myID > 1:
		# Need to remove the base load first
		baseLoad = baseLoadToSubstract[myID]
		value -= baseLoad

		if value < 0:
			value = 0.0
		
		value *= 10.0

		if value <= 0.15:
			value = 0.0

	if value <= 0.005:
		value = 0.0

	return value, val.text

# the port that we're going to use.  This can be a number or device name.
# on linux or posix systems this will look like /dev/tty2 or /dev/ttyUSB0
# on windows this will look something like COM3
#port1 = '/dev/ttyUSB' + str(readPortIndex1)
#port2 = '/dev/ttyUSB' + str(readPortIndex2)

# SCAN reading ports!
possiblePorts = [0, 1, 2, 3]
readingPorts = []

def scanReadingPorts():
	global readingPorts

	# clean ports
	for p in readingPorts:
		print "p = ", str(p)
		if p["object"]:
			try:
				print "Closing port ", p["name"]
				p["object"].close()
			except:
				continue

	readingPorts = []

	while len(readingPorts) != 2:

		del readingPorts[:]
		print "ATTEMPT TO FIND PORT"

		for p in possiblePorts:
			curPort = "/dev/ttyUSB" + str(p)

			try:
				print "trying port ", curPort
				d = tp4000zc.Dmm(curPort)

				time.sleep(0.5)
				
				print "trying to read"
				val, valText = readMulti(d)

				metric = ""

				if " volts " in valText:
					metric = "voltage"
				elif "Amps DC" in valText or "Amps AC" in valText:
					metric = "current"
				else:
					metric = "other"
				
				print "valText = ", valText

				newPort = {"name": curPort, "metric": metric, "object": d}
				readingPorts.append(newPort)
				print "adding reading port ", str(newPort)

				if len(readingPorts) >= 2:
					break
			except:
				print "Skipping port ", curPort


def sendReadings():
	global readingPorts

	msg = "READ\n"

	print "sendReadings.. readingPorts ?", str(readingPorts)

	for port in readingPorts:
		val, valText = readMulti(port["object"])

		msg += port["metric"] + "=" + str(val) + "\n"

	msg += "ENDREAD\n"

	print "sending ", msg

	dmsSock.send(msg)

def isCharging():
	if myID == 1: # no charger at this node
		return False

	if loadType1 == "charger" and loadStates[powerUSBPort1] == "on":
		return True
	elif loadType2 == "charger" and loadStates[powerUSBPort2] == "on":
		return True

	return False

def SOC():
	global batteryCapacity
	global batteryAmpsCharged

	if batteryCapacity <= 0.0:
		return 0.0

	return float(batteryAmpsCharged) / batteryCapacity

class readingMeasurement(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):
		global readingPorts
		global expectedUSBPorts
		global batteryAmpsCharged
		global previousMeasuredCurrent
		global previousMeasuredVoltage
		global shouldRefreshReaders

		tPrevious = getTime()

		while True:

			try:
				if shouldRefreshReaders:
					scanReadingPorts()
					shouldRefreshReaders = False


				if not USBPortsCorrects():
					resetUSBPorts()

				measurements = {}

				for port in readingPorts:
					val, valText = readMulti(port["object"])

					measurements[port["metric"]] = val

					if port["metric"] == "current":
						previousMeasuredCurrent = val

					if port["metric"] == "voltage":
						previousMeasuredVoltage = val
				
					logMeasurements(myID, port["metric"], val)

				if myID == 1 and "current" in measurements and "voltage" in measurements:
					# Power
					power = measurements["current"] * measurements["voltage"]			
					logMeasurements(myID, "power", power)

				secondsElapsed = float(getTime() - tPrevious) / 1000.0
				tPrevious = getTime()

				# No battery, src node
				if myID > 1 and secondsElapsed > 0.0:
					curCharged = (float(measurements["current"])) / (3600.0 / secondsElapsed)

					batteryAmpsCharged += curCharged
					logMeasurements(myID, "SOC", SOC())

				# TODO: load SOC

				#time.sleep(1)
			except Exception as e:
				logError("MULTI reading error, e = " + str(e))
				scanReadingPorts()


def sendEVRequest(evArrival, deadline, stateOfCharge, current, voltage):
	msg = "EV_REQUEST\n"
	msg += "ID=" + str(myID) + "\n"
	msg += "DEADLINE=" + str(deadline) + "\n"
	msg += "EV_ARRIVAL=" + str(evArrival) + "\n"
	msg += "SOC=" + str(stateOfCharge) + "\n"
	msg += "CURRENT=" + str(current) + "\n"
	msg += "VOLTAGE=" + str(voltage) + "\n"
	msg += "ENDEV_REQUEST\n"

	print "sending ", msg 

	dmsSock.send(msg)

def processEVResponse(variables):
	global loadType1
	global loadValue1
	global loadType2
	global loadValue2
	global powerUSBPort1
	global powerUSBPort2
	global loadStates
	global baseLoad

	print "proccess ev response, variable = ", variables


	if "START1" not in variables: # We should STOP
		# Need to turn off
		if loadType1 == "charger" and loadStates[powerUSBPort1] != "off":
			changeSwitch(powerUSBPort1, "off")

		# Need to turn off
		if loadType2 == "charger" and loadStates[powerUSBPort2] != "off":
			changeSwitch(powerUSBPort2, "off")
	else:
		# Should charge.
		rating = float(variables["RATING1"])
		deadline = strDatetimeToDatetime(variables["STOP1"])

		if loadType1 == "charger" and loadValue1 == rating:
			if loadStates[powerUSBPort1] != "on":
				changeSwitch(powerUSBPort1, "on")

			if loadType2 == "charger" and loadStates[powerUSBPort2] != "off":
				changeSwitch(powerUSBPort2, "off")
		elif loadType2 == "charger" and loadValue2 == rating:
			if loadType1 == "charger" and loadStates[powerUSBPort1] != "off":
				changeSwitch(powerUSBPort1, "off")

			if loadStates[powerUSBPort2] != "on":
				changeSwitch(powerUSBPort2, "on")

	# Base load processing
	if "SLOT" in variables:
		slotNumber = int(variables["SLOT"])

		newState = "off"

		if myID in baseLoad and slotNumber in baseLoad[myID]:
			# Need to switch ON
			newState = "on"

		if loadType1 == "load" and loadStates[powerUSBPort1] != newState:
			changeSwitch(powerUSBPort1, newState)
		elif loadType2 == "load" and loadStates[powerUSBPort2] != newState: 
			changeSwitch(powerUSBPort2, newState)


def USBPortsCorrects():
	for port in expectedUSBPorts:
		cur = "/dev/ttyUSB" + str(port)

		if not os.path.exists(cur):
			return False

	return True

def resetUSBPorts():
	# First, close the controllable switches
	id = 1

	logError("RESET USB PORTS !!! ")

	for i in range(len(expectedUSBPorts)):
		changeSwitch(id, "off")

		id += 1

	nbTrials = 0
	maxNbTrials = 3

	while True:
		# Then, reset usb ports (power)
		cmd = "sudo bash /home/pi/smart-grid-lab/resetUSB.sh"
		print "Exec ", cmd
		os.system(cmd)

		if USBPortsCorrects():
			# OK, fine.
			break

		# Wait 
		time.sleep(2)

		nbTrials += 1

		if nbTrials >= maxNbTrials:
			raise Exception("TOO MANY USB RECONNECT TRIALS")
			sys.exit(0)

	# Rescan reading ports
	scanReadingPorts()

	# TODO: put back the controllable switches to the original state
	for loadState in loadStates:
		changeSwitch(loadState, loadStates[loadState])
		
def changeSwitch(port, newState):
	global loadStates
	global CMD_CNTRL_LOAD

	loadStates[port] = newState
	print "LOAD STATES = ", loadStates
	cmdChg = CMD_CNTRL_LOAD + " " + newState + " " + str(port)
	print "Exec ", cmdChg
	logEvent("Switching " + cmdChg)
	os.system(cmdChg)
	time.sleep(1)
	cmd = CMD_CNTRL_LOAD + " status " + str(port)
	print "Exec check ", cmd
	output = subprocess.check_output(cmd, shell=True).strip()
	time.sleep(1)

	if output.upper() != newState.upper():
		logError("Switch state did not change correctly .. " + cmdChg)
		print "REExec ", cmdChg
		logEvent("Switching " + cmdChg)
		os.system(cmdChg)
		time.sleep(1)
		

 #Return format:
# mode, {variable => value}
def decodeMsg(msg):
	elements = msg.split("\n")

	mode = ""

	variables = {}

	for e in elements:
		if len(e) <= 0:
			continue

		if e == "MEASUREMENT" or e == "EV_RESPONSE":
			mode = e
			continue

		if e == "ENDMEASUREMENT" or e == "ENDEV_RESPONSE":
			continue

		print "cur element = ", e

		variable, value = e.split("=")

		variables[variable] = value

	return mode, variables

def checkArrivalRequest():
	global EVArrived
	global dtArrival
	global dtDeadline

	if not EVArrived:

		if dtArrival == None or dtDeadline == None:
			dtArrival = addSecsDateTime(arrivalTime)
			dtDeadline = addSecsDateTime(deadline)

		print " ==================================================== curdatetime ", str(curDateTime())
		print "dtArrival = ", str(dtArrival)

		if curDateTime() >= dtArrival:
			print "OK cur time > arrival"

			# SEND request !!!!!!
			#sendEVRequest(dtDeadline)

			#recvMsg = dmsSock.recv(BUFFER_SIZE)

			#mode, variables = decodeMsg(recvMsg)

			#print "received ", recvMsg
			#print "variables = ", str(variables)

			EVArrived = True
			print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

if myID != 1:
	changeSwitch(powerUSBPort1, "off")
	changeSwitch(powerUSBPort2, "off")

if not USBPortsCorrects():
	print "USB ports not corrects, resetting."
	resetUSBPorts()

scanReadingPorts()

reader = readingMeasurement()
reader.start()

while True:
	
	mode = ""

	try:


		if measurementType == "coordinated":
			measurementMsg = dmsSock.recv(BUFFER_SIZE)

			print "should decode ", measurementMsg

			mode, variables = decodeMsg(measurementMsg)

			# mode could be different

			if mode == "MEASUREMENT":
				timeFromDMS = variables["TIME"]
				logEvent("Received measurement, time = " + str(timeFromDMS))

				if len(timeFromDMS) > 0:
					cmdDate = "sudo date -s '" + timeFromDMS + "'"
					print "Exec", cmdDate
					os.system(cmdDate)

			print "coord msg from dms, mode = ", mode, " variables = ", variables

		checkArrivalRequest()

		if measurementType == "upstream" or (measurementType == "coordinated" and mode == "MEASUREMENT"):
			# we need to charge
			print "WE SHOULD CHARGE !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
			sendEVRequest(dtArrival, dtDeadline, SOC(), previousMeasuredCurrent, previousMeasuredVoltage)
			logEvent("EV request, soc = " + str(SOC()) + " current = " + str(previousMeasuredCurrent))

			recvMsg = dmsSock.recv(BUFFER_SIZE)

			mode, variables = decodeMsg(recvMsg)

			print "received ", recvMsg
			print "variables = ", str(variables)

			if myID != 1:
				for trial in [1, 2, 3, 4]:
					try:
						print "Processing EV response !!"
						processEVResponse(variables)
						break
					except Exception as e:
						logError("problem process ev .. e = " + str(e))
						# Reset ports
						resetUSBPorts()
						# switch off
						changeSwitch(powerUSBPort1, "off")
						changeSwitch(powerUSBPort2, "off")
						loadStates[powerUSBPort1] = "off"
						loadStates[powerUSBPort2] = "off"

			shouldRefreshReaders = True

		if measurementType == "upstream":
			time.sleep(1)

	except Exception as e:
		print "error", traceback.format_exc()

#if dmsSock != None:
#	dmsSock.close()


