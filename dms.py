import socket
import threading
import sys
import os
sys.path.insert(1, os.path.join(sys.path[0], '..'))
import time
import datetime
import signal

import curses
from util import *

INPUT_MATLAB_FILE = "/home/zeitgeist/smart-grid-lab/dms/matlab/input"
OUTPUT_MATLAB_FILE = "/home/zeitgeist/smart-grid-lab/dms/matlab/output"

emptyMeasurements()
emptyEvents()
emptyErrors()
emptyFile(INPUT_MATLAB_FILE)
emptyFile(OUTPUT_MATLAB_FILE)
signal.signal(signal.SIGINT, signal_handler)

startTime = curDateTime()
beginSlot = getTime()

IP = "192.168.1.81"
PORT = 5005

LOG_MEASUREMENTS = True
EXPR_SLOT_DURATION = 900
SLOT_DURATION = 40
RATIO_SLOT_DURATION = float(SLOT_DURATION) / float(EXPR_SLOT_DURATION)
EV_IDs = [2, 3, 4, 6, 7, 8, 9, 10, 11, 12]
soc_initial = [0,  0.35,    0.05,    0.25,    0,       0.12,    0.1,     0.22,    0.16,    0.24,    0.2,     0.28] # TODO
# TODO: add soc + LOG !!

maxShownEvents = 15
screenEventList = []

def addEvent(desc):
	now = time.strftime("%Y-%m-%d %H:%M:%S")

	if len(screenEventList) >= maxShownEvents:
		del screenEventList[0]

	if len(desc) > 95:
		desc = desc[0:95] + "..."

	desc += " " * (98 - len(desc))
	
	screenEventList.append("%s: %s" % (now, desc))

	logEvent(desc)

def relativeTime():
	global startTime

	t = curDateTime() - startTime

	return t.total_seconds()

# Check arguments
if len(sys.argv) != 5:
	terminate("Command: python dms.py <MY IP> <MY PORT> <upstream/coordinated> <randomCharging>")

IP = sys.argv[1]
PORT = int(sys.argv[2])
MEASUREMENT_TYPE = sys.argv[3] # upstream/coordinated
scenario = sys.argv[4] # randomCharging

infosSmartNodes = {}

cmdMatlab = "cd /home/zeitgeist/smart-grid-lab/dms/matlab && /home/zeitgeist/travaux/programmes/MATLAB2011b/bin/matlab -nojvm -nodesktop -nosplash -r \"run()\" > dump &"
addEvent("Exec " + cmdMatlab)
os.system(cmdMatlab)
addEvent("Starting")

BUFFER_SIZE = 10024

# Connection to smart node
class remoteNode(threading.Thread):
	def __init__(self, conn, addr):
		threading.Thread.__init__(self)
		self.conn = conn
		self.addr = addr
		self.idNode = ""
		self.request = {}

	

	def run(self):
		self.idNode = ""

		while True:
			rcvMsg = ""

			try:
				rcvMsg = self.conn.recv(BUFFER_SIZE)
			except Exception as e:
				print "DROPPED ADDR", self.addr, " error = ", str(e)
				terminate("connection err")

			rcvElements = rcvMsg.split("\n")

			if len(rcvElements) < 2:
				terminate("Problem reading phase, missing elements ?")

			mode = ""
			evRequestInfos = {}

			for e in rcvElements:

				if len(e) <= 0:
					continue

				if e == "INIT" or e == "READ" or e == "EV_REQUEST":
					mode = e
					continue

				if e == "ENDINIT" or e == "ENDREAD" or e == "ENDEV_REQUEST":
					continue

				variable, value = e.split("=")

				if mode == "INIT":
					if variable == "ID":
						self.idNode = value
						infosSmartNodes[value] = {} # create row for the new node
						infosSmartNodes[value]["CURRENT"] = 0.0
						infosSmartNodes[value]["SOC"] = 0.0
						infosSmartNodes[value]["VOLTAGE"] = 0.0
						infosSmartNodes[value]["IP"] = str(self.addr)

						addEvent("Adding node %s (%s)" % (value, str(self.addr)))
					else:
						infosSmartNodes[self.idNode][variable] = value
				elif mode == "READ":
					logMeasurements(self.idNode, variable, value)
					
					if variable == "current":
						infosSmartNodes[self.idNode]["CURRENT"] = float(value)
					elif variable == "voltage":
						infosSmartNodes[self.idNode]["VOLTAGE"] = float(value)

				elif mode == "EV_REQUEST":
					if variable in ["ID", "DEADLINE", "EV_ARRIVAL", "SOC", "CURRENT", "VOLTAGE"]:
						evRequestInfos[variable] = value

						if "ID" in evRequestInfos and "DEADLINE" in evRequestInfos and "EV_ARRIVAL" in evRequestInfos and "SOC" in evRequestInfos and "CURRENT" in evRequestInfos and "VOLTAGE" in evRequestInfos:
							# we received all infos
					
							#deadline = strDatetimeToDatetime(evRequestInfos["DEADLINE"])
							#arrival = strDatetimeToDatetime(evRequestInfos["EV_ARRIVAL"])
							soc = float(evRequestInfos["SOC"]) / RATIO_SLOT_DURATION
							current = evRequestInfos["CURRENT"]
							voltage = evRequestInfos["VOLTAGE"]

							infosSmartNodes[self.idNode]["SOC"] = float(soc)
							infosSmartNodes[self.idNode]["CURRENT"] = float(current)
							infosSmartNodes[self.idNode]["VOLTAGE"] = float(voltage)

							#self.request["deadline"] = deadline
							#self.request["arrival"] = arrival
							self.request["soc"] = soc + soc_initial[int(self.idNode)-1]
							self.request["current"] = current

							addEvent("Received EV request from " + str(self.idNode) + " soc = " + str(soc) + ", current = " + str(current))
							
							evRequestInfos = {}

			if mode == "READ":
				operationToDo = "nothing"
				self.conn.send(operationToDo)

class measurementBroadcaster(threading.Thread):
	def __init__(self, nodeThreads):
		threading.Thread.__init__(self)
		self.nodeThreads = nodeThreads
		self.previousSocs = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
		self.slot = 1

	def sendEVResponse(self, thread, reservedSlots):
		msg = "EV_RESPONSE\n"
		msg += "SLOT=" + str(self.slot) + "\n"

		index = 1

		for slot in reservedSlots:
			msg += "START" + str(index) + "=" + slot["start"] + "\n"
			msg += "STOP" + str(index) + "=" + slot["stop"] + "\n"
			msg += "RATING" + str(index) + "=" + str(slot["rating"]) + "\n"

			index += 1

		msg += "ENDEV_RESPONSE\n"


		thread.conn.send(msg)

	def schedule(self, thread, decisionResult):
		nodeId = int(thread.idNode)

		rating = decisionResult[nodeId-1]

		if rating > 0:
			reservedSlots = [{"start": str(curDateTime()), "stop": str(addSecsDateTime(SLOT_DURATION)), "rating": rating}]
		else:
			reservedSlots = []

		return reservedSlots

	def run(self):
		global beginSlot

		while True:
			if self.slot > 96:
				break

			addEvent("Start of SLOT " + str(self.slot))

			time.sleep(SLOT_DURATION) # 10 for the sleep

			beginSlot = getTime()

			msg = "MEASUREMENT\n"
			msg += "TIME=" + getSTime() + "\n"
			msg += "ENDMEASUREMENT\n"

			for thread in self.nodeThreads:
				thread.conn.send(msg)

			allRequestsReceived = False

			while not allRequestsReceived:

				allRequestsReceived = True

				for thread in self.nodeThreads:
					if thread.request == {}:
						allRequestsReceived = False
						break

			# checkfunction(t, socs, previous_socs, currents)
			t = self.slot
			socs = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
			currents = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

			for thread in self.nodeThreads:
				socs[int(thread.idNode)-1] = float(thread.request["soc"])
				currents[int(thread.idNode)-1] = float(thread.request["current"])

				logMeasurements("N=" + str(thread.idNode), "SOC", thread.request["soc"])

				thread.request = {}

			# (t, socs, previous_socs, currents)

			t1 = getTime()

			#matlabCode = "checkfunction(" + str(t) + ", " + str(socs) + ", " + str(self.previousSocs) + ", " + str(currents) + ")"
			matlabCode = "optfunction(2, " + str(t) + ", " + str(socs) + ")"

			logEvent(matlabCode)

			addEvent("Matlab " + matlabCode)
			emptyFile(INPUT_MATLAB_FILE)
			emptyFile(OUTPUT_MATLAB_FILE)
			appendFile(INPUT_MATLAB_FILE, matlabCode)

			#print "matlab command ", matlabCode

			# Then we need to wait for the output file !
			output = ""

			while output == "":
				output = getFile(OUTPUT_MATLAB_FILE).strip()
				time.sleep(0.001)

			#print "OUTPUT IS -" + output + "-"

			decisionResult = eval(output)
			#print "decision result = -"+ str(decisionResult) + "-"

			t2 = getTime()

			computation = float(t2 - t1) / 1000.0
			logMeasurements("N/A", "computation", computation)

			addEvent("Calc optim. " + str(decisionResult) + " It took: " + str(computation))

			# then for each EV we need to schedule
			for thread in self.nodeThreads:
				reservedSlots = self.schedule(thread, decisionResult)
				self.sendEVResponse(thread, reservedSlots)
				#time.sleep(2)

			#reservedSlots = []

			#if scenario == "randomCharging":
			#	reservedSlots = self.scheduleRandomCharging(deadline)

			#self.sendEVResponse(reservedSlots)

			# Keep track of the previous SOCs
			self.previousSocs = socs[:]
			self.slot += 1

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((IP, PORT))
s.listen(20) # param = maximum nb of pending conn

nbNodesCreated = 0

###############################
# Nodes creation

listNodeThreads = []

while nbNodesCreated != 11: # complete = 11
	conn, addr = s.accept()

	t = remoteNode(conn, addr)

	listNodeThreads.append(t)

	t.start()
	nbNodesCreated += 1

# Then, we start the broadcaster if it is type coordinated
coordinator = None


if MEASUREMENT_TYPE == "coordinated":
	coordinator = measurementBroadcaster(listNodeThreads)

	coordinator.start()

##############################
# Output 

def formatIDNb(n):
	if n < 10:
		return "0" + str(n)

	return "" + str(n)

def nodeToString(nodeID):

	if nodeID == -1:
		return "||                                      ||"

	if str(nodeID) in infosSmartNodes:
		current = infosSmartNodes[str(nodeID)]["CURRENT"]
		soc = infosSmartNodes[str(nodeID)]["SOC"]
		v = infosSmartNodes[str(nodeID)]["VOLTAGE"]
	else:
		current = 0.0
		soc = 0.0
		v = 0.0

	value = 0.0

	if nodeID == 1:
		value = current
	else:
		value = soc

	s = "|| Node %s: A/S=%.3f V=%.1f           ||" % (formatIDNb(nodeID), value, v)

	return s


def refreshScreen(window):
	global beginSlot 

	while True:

		
		durationSlot = float(getTime() - beginSlot) / 1000.0

		# y, x
		window.addstr(5, 60, "S-M-A-R-T G-R-I-D L-A-B")
		window.addstr(7, 60, "SLOT " + str(coordinator.slot) + ". Time from beginning of slot: " + str(durationSlot))

		# Rack box
		window.addstr(9, 50, "                 Left rack                                   Right rack                ")
		window.addstr(10, 50, "------------------------------------------  ------------------------------------------")
		window.addstr(11, 50, "%s  %s" % (nodeToString(4), nodeToString(12)))
		window.addstr(12, 50, "%s  %s" % (nodeToString(3), nodeToString(11)))
		window.addstr(13, 50, "%s  %s" % (nodeToString(1), nodeToString(10)))
		window.addstr(14, 50, "%s  %s" % (nodeToString(2), nodeToString(9)))
		window.addstr(15, 50, "%s  %s" % (nodeToString(6), nodeToString(8)))
		window.addstr(16, 50, "%s  %s" % (nodeToString(7), nodeToString(-1)))
		window.addstr(17, 50, "------------------------------------------  ------------------------------------------")

		# Event box
		window.addstr(20, 10, "----------------------------------------------")
		window.addstr(21, 10, "-              LATEST EVENTS")

		lineNumber = 22

		for e in reversed(screenEventList):
			window.addstr(lineNumber, 10, "- %s" % e)

			lineNumber += 1

		window.refresh()
		time.sleep(0.5)
		
curses.wrapper(refreshScreen)

#while True:
#	time.sleep(10)



