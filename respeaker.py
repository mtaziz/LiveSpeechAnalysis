import pyaudio
import Queue
from threading import Thread
import numpy as np
from gcc_phat import gcc_phat
import math
import audioop
import time
import wave
from collections import deque
from pixels import pixels
import csv
import sys
import os
import ntplib
from speech_analysis import speech_2_text

SOUND_SPEED = 340


MIC_DISTANCE_4 = 0.081
MAX_TDOA_4 = MIC_DISTANCE_4 / float(SOUND_SPEED)

DIRECTIONS_QUEUE = Queue.Queue()
AUDIO_QUEUE = Queue.Queue()

try:
	client = ntplib.NTPClient()
	response = client.request('pool.ntp.org')
	print time.localtime(response.tx_time)
	os.system('date ' + time.strftime('%m%d%H%M%Y.%S', time.localtime(response.tx_time)))
except:
	print('Could not sync with time server.')

print('Done.')

class MicArray(object):
	def __init__(self, rate=16000, channels=4, chunk_size=None):
		self.FORMAT = pyaudio.paInt16
		self.CHANNELS = channels
		self.RATE = rate
		self.CHUNK = chunk_size if chunk_size else 1024
		self.pyaudio_instance = pyaudio.PyAudio()
		self.SILENCE_LIMIT = 5
		self.PREV_AUDIO = 0.5
		self.THRESHOLD = 800
		self.queue = Queue.Queue()

	# Need to sort out setting threshold for 4 mic array
	def setup_mic(self, num_samples=50):
		# Gets average audio intensity of your mic sound.
		print "Getting intensity values from mic."
		device_index = None
		for i in range(self.pyaudio_instance.get_device_count()):
			dev = self.pyaudio_instance.get_device_info_by_index(i)
			name = dev['name'].encode('utf-8')
			if dev['maxInputChannels'] == self.CHANNELS:
				device_index = i
				break

		if device_index is None:
			raise Exception('can not find input device with {} channel(s)'.format(self.CHANNELS))

		p = pyaudio.PyAudio()
		stream = p.open(
			input=True,
			format=self.FORMAT,
			channels=self.CHANNELS,
			rate=self.RATE,
			frames_per_buffer=self.CHUNK,
			input_device_index=device_index,
		)
		values = [
			math.sqrt(abs(audioop.avg(stream.read(self.CHUNK), 4)))
			for x in range(num_samples)]
		values = sorted(values, reverse=True)
		r = sum(values[:int(num_samples * 0.2)]) / int(num_samples * 0.2)
		print " Finished getting intensity values from mic"
		stream.close()
		p.terminate()
		return r

	def record_to_file(self, recording_name):
		file_writer = open('recordings.txt', 'a')
		file_writer.write(recording_name + "\n")

	def save_speech(self):
		while True:
			t_tuple = None
			if not AUDIO_QUEUE.empty():
				t_tuple = AUDIO_QUEUE.get()
				data = t_tuple[1]
				time_recorded = t_tuple[0]
				if data is not None:
					p = self.pyaudio_instance
					filename = self.convert_time(time_recorded)
					self.record_to_file(filename + ".wav")
					data = ''.join(data)
					wf = wave.open('./audio_files/' + filename + '.wav', 'wb')
					wf.setnchannels(4)
					wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
					wf.setframerate(self.RATE)
					wf.writeframes(data)
					wf.close()
					print speech_2_text(filename + ".wav")
			else:
				time.sleep(25)

		print 'Exiting save audio...'

	def get_direction(self, buf):
		best_guess = None
		if self.CHANNELS == 4:
			MIC_GROUP_N = 2
			MIC_GROUP = [[0, 2], [1, 3]]

			tau = [0] * MIC_GROUP_N
			theta = [0] * MIC_GROUP_N
			for i, v in enumerate(MIC_GROUP):
				tau[i], _ = gcc_phat(buf[v[0]::4], buf[v[1]::4], fs=self.RATE, max_tau=MAX_TDOA_4, interp=1)
				theta[i] = math.asin(tau[i] / MAX_TDOA_4) * 180 / math.pi

			if np.abs(theta[0]) < np.abs(theta[1]):
				if theta[1] > 0:
					best_guess = (theta[0] + 360) % 360
				else:
					best_guess = (180 - theta[0])
			else:
				if theta[0] < 0:
					best_guess = (theta[1] + 360) % 360
				else:
					best_guess = (180 - theta[1])

				best_guess = (best_guess + 90 + 180) % 360

			best_guess = (-best_guess + 120) % 360
		elif self.CHANNELS == 2:
			pass
		return best_guess

	def get_direction_helper(self, frames):
		frames = np.fromstring(frames, dtype='int16')
		direction = self.get_direction(frames)
		return direction

	def record_time_stamp(self):
		while True:
			t_tuple = None
			if not DIRECTIONS_QUEUE.empty():
				t_tuple = DIRECTIONS_QUEUE.get()
				frames = t_tuple[0]
				time_recorded = t_tuple[1]
				try:
					direction = self.get_direction_helper(frames)
					pixels.wakeup(direction)
					print direction
					self.record_time_stamp2(self.convert_time(time_recorded), direction)
				except:
					print 'could not get direction'
					continue
			else:
				time.sleep(5)
		print 'Exiting recording time stamps'

	def record_time_stamp2(self, time_of_recording, direction):
		with open('direction_time_stamps.csv', 'ab') as csv_file:
			direction_writer = csv.writer(csv_file, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
			direction_writer.writerow([time_of_recording, direction])

	def convert_time(self, time_to_convert):
		date_val = time.ctime(time_to_convert).split()
		return date_val[3].replace(':','')

	def run(self, num_phrases=-1):
		p = self.pyaudio_instance
		device_index = None
		print 'Setting up pyaudio ...'
		for i in range(self.pyaudio_instance.get_device_count()):
			dev = self.pyaudio_instance.get_device_info_by_index(i)
			name = dev['name'].encode('utf-8')
			if dev['maxInputChannels'] == self.CHANNELS:
				print('Using {}'.format(name))
				device_index = i
				break

		if device_index is None:
			raise Exception('can not find input device with {} channel(s)'.format(self.CHANNELS))

		stream = p.open(
			input=True,
			format=self.FORMAT,
			channels=self.CHANNELS,
			rate=int(self.RATE),
			frames_per_buffer=int(self.CHUNK),
			input_device_index=device_index,
		)

		print "* Listening mic..."
		audio2send = []
		cur_data = ''
		rel = int(self.RATE / self.CHUNK)
		slid_win = deque(maxlen=self.SILENCE_LIMIT * rel)

		# Prepend audio from 0.5 seconds before noise was detected
		prev_audio = deque(maxlen=self.PREV_AUDIO * rel)
		started = False
		n = num_phrases
		response = []
		time_counter = time.time()
		save_time_counter = time.time()
		while num_phrases == -1 or n > 0:
			try:
				cur_data = stream.read(self.CHUNK)
				slid_win.append(math.sqrt(abs(audioop.avg(cur_data, 4))))
				if sum([x > self.THRESHOLD for x in slid_win]) > 0:
					if not started:
						print "Starting record of phrase..."
						started = True
					audio2send.append(cur_data)
					frames = audio2send[len(audio2send)-2]
					if frames:
						if time.time()-time_counter >= 5:
							time_counter = time.time()
							DIRECTIONS_QUEUE.put((frames, time.time(),))
					if time.time()-save_time_counter >= 120:
						save_time_counter = time.time()
						AUDIO_QUEUE.put((save_time_counter,list(prev_audio) + audio2send,))
						started = False
						slid_win = deque(maxlen=self.SILENCE_LIMIT * rel)
						prev_audio = deque(maxlen=0.5 * rel)
						audio2send = []
						n -= 1
						print 'Listening ...'
				elif started:
					print "Finished"
					save_time_counter = time.time()
					AUDIO_QUEUE.put((save_time_counter, list(prev_audio) + audio2send,))
					frames = audio2send[len(audio2send)-2]
					if frames:
						DIRECTIONS_QUEUE.put((frames, save_time_counter,))
					started = False
					slid_win = deque(maxlen=self.SILENCE_LIMIT * rel)
					prev_audio = deque(maxlen=0.5 * rel)
					audio2send = []
					n -= 1
					print "Listening ..."
				else:
					prev_audio.append(cur_data)
			except KeyboardInterrupt:
				print 'saving last file before exit...'
				end_time = time.time()
				AUDIO_QUEUE.put((end_time, list(prev_audio) + audio2send,))
				frames = audio2send[len(audio2send) - 2]
				if frames:
					DIRECTIONS_QUEUE.put((frames, end_time,))
				sys.exit()
		print "* Done recording...Exiting..."
		stream.close()
		p.terminate()


if __name__ == '__main__':
	sd = MicArray()
	t1 = Thread(target = sd.run)
	t2 = Thread(target = sd.record_time_stamp)
	t3 = Thread(target = sd.save_speech)
	t1.start()
	t2.start()
	t3.start()
	t1.join()
	t2.join()
	t3.join()

