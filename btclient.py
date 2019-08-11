import argparse
import bencodepy
import os
from urllib import request
from urllib import parse
import logging
import struct
import socket
import signal
import sys
import threading
import utils
import time

MY_PORT = 6968
PROTOCOL_ID = 0x41727101980
TRANSACTION_ID = 123
MAX_NUMB_PEERS = 10
PIECE_SIZE = 16384

def signal_handler(code, frame):
	RUNNING = False
	sys.exit()

def get_response(ip, port, request):
	udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	resp = None
	tries = 4
	while True:
		udp_socket.sendto(request, (ip, port))
		udp_socket.settimeout(5)
		try:
			resp = udp_socket.recv(256)
			break
		except socket.timeout:
			tries -= 1
			if tries > 0:
				continue
			else:
				return None

	return resp



def connect_udp_tracker(info_hash, peer_id, length):
	announce = my_ordred_dict[b'announce']
	host = announce.split(b'/')[2]
	name, port = host.split(b':')
	ip = socket.gethostbyname(name)

	request = utils.get_connect_request()
	response = get_response(ip, int(port), request)
	if  response and len(response) >= 16:
		action, tr_id, con_id = struct.unpack('!IIQ',response)
		if tr_id != TRANSACTION_ID or action != 0 :
			return
		
		request = utils.get_announce_request(con_id, info_hash, peer_id, length)
		response = get_response(ip, int(port),  request)
		if response and len(response) >= 20:
			ip, port = utils.get_address(response)
			return (ip, port)
		else:
			return None



def connect_tracker(dict_hash, peer_id):
	announce = my_ordred_dict[b'announce'].decode()
	if announce.startswith('http'):
		payload = {'info_hash': dict_hash, 'peer_id': peer_id, 
				'port': MY_PORT, 'evented': 'started', 
				'uploaded' : '0', 'downloaded' : '0',  'left': str(full_length), 'compact': '1', 'numwant' : '100'}

		full_url = "{}?{}".format(announce, parse.urlencode(payload))
		req = request.Request(full_url)
		req.method = "GET"
		http_resp = request.urlopen(req)
						
		if http_resp:
			resp = http_resp.read()
			if b'failure reason' not in resp: 
				answer_dict = bencodepy.decode(resp)
				return utils.decode_peers(answer_dict[b'peers'])
			else:
				print("failure in connecting to tracker")	
		else:
			print("Can't Connect Tracker")
		
	else:
		peer_address = connect_udp_tracker(dict_hash, peer_id, length)
		if not peer_address:
			print("Can't Connect Tracker")
		else:	
			return [(peer_address)]
		
def read_file(cur_file, pointer, piece_length, size, index):
	piece = b''
	while pointer + piece_length < size:
		cur_file.seek(pointer)
		piece = cur_file.read(piece_length)
		if utils.compute_hash(piece) == pieces[index]:
			downloaded_pieces[index] = 1
			index += 1
	
		pointer += piece_length

	if size > 0:
		cur_file.seek(pointer)
		piece = cur_file.read()
		return piece, index

	return b'', index	

def check_partial_torrent():	
	numb_pieces = len(pieces)
	piece_length = my_ordred_dict[b'info'][b'piece length']


	if MULTI_FILE:
		index = 0
		piece = b''
		for size, path in files:
			if os.path.exists(path):				
				with open(path, 'r+b') as cur_file:
					pointer = 0
					if len(piece) > 0:
						left_to_piece = piece_length - len(piece)
						if left_to_piece < size:
							piece += cur_file.read(left_to_piece)
							if len(piece) == piece_length:
								if utils.compute_hash(piece) == pieces[index]:
									downloaded_pieces[index] = 1
									index += 1

							pointer = left_to_piece
							size = size - left_to_piece
							piece, index = read_file(cur_file, pointer, piece_length, size, index)
							
						else:
							piece += cur_file.read()
							if len(piece) == piece_length:
								if utils.compute_hash(piece) == pieces[index]:
									downloaded_pieces[index] = 1
									index += 1
							continue

					else:

						piece, index = read_file(cur_file, pointer, piece_length, size, index)
			
		if len(piece) > 0:
			if utils.compute_hash(piece) == pieces[index]:
				downloaded_pieces[index] = 1

	else:
		if os.path.exists(save_directory + "/" + file):			
			with open(save_directory + "/" + file, "r+b") as cur_file:
				for i in range(numb_pieces):
					cur_file.seek(i * piece_length)
					piece = cur_file.read(piece_length)

					if utils.compute_hash(piece) == pieces[i]:
						downloaded_pieces[i] = 1
					



def send_request(bitfield, peer_socket, my_pieces):
	for i in range(len(bitfield)):
		if bitfield[i] == 1:  # if peer has piece
			try:
				pieces_lock.acquire()
				if downloaded_pieces[i] == 0:
					downloaded_pieces[i] = 1					
					pieces_lock.release()
					my_pieces[i] = b''
					utils.send_piece_numb(peer_socket = peer_socket, index = i, length = PIECE_SIZE)
					break
				else:
					pieces_lock.release()
			except:
				break



def write_block_in_file(block, index, begin):
	length = len(block)
	new_bytes  = len(block)
	begin = my_ordred_dict[b'info'][b'piece length'] * index
	if MULTI_FILE:
		for file_size, dir_file in files:
			if file_size < begin:
				begin -= file_size
			else:
				with open(dir_file, "r+b") as cur_file:
					if begin + length < file_size:
						cur_file.seek(begin)
						cur_file.write(block)
						break
					else:
						cur_file.seek(begin)
						to_write = file_size - begin

						cur_file.write(block[:to_write])
						block = block[to_write:]
						length -= to_write
						begin = 0

	else:
		with open(save_directory + "/" + file, "r+b") as cur_file:	
			cur_file.seek(begin)
			cur_file.write(block)

	with lock:
		# print (threading.current_thread(), index)
		global downloaded_bytes
		downloaded_bytes += new_bytes

def unpack_piece(raw_data, my_pieces, peer_socket, bitfield):
	
	try:
		index, begin = struct.unpack('!II', raw_data[:8])
		block = raw_data[8:]
		my_pieces[index] += block
		prev_bytes = my_ordred_dict[b'info'][b'piece length'] * index
		#last piece of data
		global downloaded_bytes
	
		lock.acquire()
		
		if len(my_pieces[index]) == my_ordred_dict[b'info'][b'piece length'] or ((index == len(pieces) - 1 and  prev_bytes + len(my_pieces[index]) == full_length)): 
			lock.release()
			if utils.compute_hash(my_pieces[index]) == pieces[index]:				
				write_block_in_file(my_pieces[index], index, begin)
				if sum(downloaded_pieces) != len(pieces):
					send_request(bitfield, peer_socket, my_pieces)
					return False
				else:
					return True
			else:	
				with pieces_lock:
					try:
						downloaded_pieces[index] = 0
					except KeyboardInterrupt:
						return True
				print("hash wasn't correct ")
				return True
		else:
			lock.release()	
			
			if index == len(pieces) - 1 and  prev_bytes + len(my_pieces[index]) + PIECE_SIZE > full_length:
				last_piece_size = full_length - prev_bytes - len(my_pieces[index])
				if last_piece_size == 0: return False
				utils.send_piece_numb(peer_socket = peer_socket, index = index, length = last_piece_size, begin = len(my_pieces[index]))
			else:
				utils.send_piece_numb(peer_socket = peer_socket, index = index, length = PIECE_SIZE, begin = len(my_pieces[index]))
			return False
			
	except:
		lock.release()
		return True


def process_data(raw_data, bitfield, my_pieces,  peer_socket):
	try:
		if 5 == struct.unpack('!B', raw_data[:1])[0]:
			bitfield += utils.get_bitfield_data(raw_data)
			with pieces_lock:	
				if utils.interested(bitfield, downloaded_pieces):
					utils.send_interested(peer_socket)
				else:
					utils.send_not_interested(peer_socket)
					return True
				

		if 4 == struct.unpack('!B', raw_data[:1])[0]:
			utils.set_have(raw_data, bitfield)	
			return False

		if 1 == struct.unpack('!B', raw_data[:1])[0]:
			if bitfield:
				send_request(bitfield, peer_socket, my_pieces)
			return False

		if 0 == struct.unpack('!B', raw_data[:1])[0]:
			return True

		if 7 == struct.unpack('!B', raw_data[:1])[0]:
			return unpack_piece(raw_data[1:], my_pieces, peer_socket, bitfield)



		return False

	except:
		return True


def restore_info(my_pieces):
	# print("restoring info")
	for index, piece in my_pieces.items():
		if len(piece) < my_ordred_dict[b'info'][b'piece length']:
			try:
				pieces_lock.acquire()
				downloaded_pieces[index] = 0
			except:
				pass
			finally:
				pieces_lock.release()	




def download_data(peer_socket, peer):
	peer_socket.settimeout(5)
	bitfield = []
	my_pieces = {}

	try:
		while True:	
			data = b''
			while len(data) < 4:
				new_data = peer_socket.recv(4 - len(data))
				if new_data == b'':
					continue
				data += new_data
				peer_socket.settimeout(5)


			msg_length = struct.unpack('!I', data)[0]

			if msg_length == 0:
				continue
			data = b''
			while msg_length > 0:
				raw_data = peer_socket.recv(msg_length)
				if raw_data == b'': 
					break
				peer_socket.settimeout(5)
				data += raw_data
				msg_length -= len(raw_data) 

			peer_socket.settimeout(None)
			choked = process_data(data, bitfield,  my_pieces, peer_socket)
			if choked:
				if sum(downloaded_pieces) != len(pieces): 
					restore_info(my_pieces)

				break

	except (socket.timeout, OSError):
		restore_info(my_pieces)
		# print("downloading paused")




def connect_to_peer(peer):
	handshake = utils.get_handshake(dict_hash, my_peer_id)
	peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	try:
		peer_socket.connect(peer)
		peer_socket.sendall(handshake)
		peer_socket.settimeout(5) 
		interested = peer_socket.recv(len(handshake))
		if interested:
			if dict_hash == struct.unpack('!20s', interested[28:48])[0]:
				with lock:
					connected_peers.append(peer)
					
				peer_socket.settimeout(None)
				download_data(peer_socket, peer)
			else:
				peer_socket.close()	
			
			
	except (socket.timeout, OSError):
		print("timeout while connecting to peer")
		
	peer_socket.close()
	with lock:	
		# print("one of the peer ended working")
		if peer in connected_peers:
			connected_peers.remove(peer)
		
			

def download():
	if sum(downloaded_pieces) != len(pieces):
		print( "---- Connecting tracker ---- " )
		peers_ips = connect_tracker(dict_hash, my_peer_id)
		if len(peers_ips) > 0:
			print("---- Connecting peers ----")
			global thread_i
			while True:
				try:
					lock.acquire()
					if thread_i < len(peers_ips) and len(connected_peers) < MAX_NUMB_PEERS and downloaded_bytes != full_length:
						lock.release()
						peer = peers_ips[thread_i]
						threading.Thread(target=connect_to_peer, args=(peer,), daemon = True).start()
						thread_i += 1
						time.sleep(5)
					else:
						lock.release()
						if downloaded_bytes == full_length or thread_i == len(peers_ips):
							connected_peers.clear()
							break
						time.sleep(5)
					
				except :
					print("Downloading stopped")
					break
	
		
				

def log_info():
	import datetime
	start_time = datetime.datetime.now()
	while True:
		time.sleep(logging_time)
		percent = (downloaded_bytes / full_length) * 100
		if percent > 100: percent = 100
		if MULTI_FILE:
			print("FILE: {0:} ({1:.2f} %)".format(root_directory, percent))
		else:
			print("FILE: {0:} ({1:.2f} %)".format(file, percent))

		if verbose:
			print("    S: {}, L: {}".format(len(connected_peers), leachers))
			print("    D: {}KB".format(int(downloaded_bytes/1000)))
			time_diff = str(datetime.datetime.now() - start_time)
			print("    elapsed: {}".format(time_diff[0:time_diff.find('.')]))


parser = argparse.ArgumentParser()
parser.add_argument("torrent_file", help="path to torrent file")
parser.add_argument("directory", help="path to save directory")
parser.add_argument("-v", "--verbose", help="for meta info", action="store_true")
parser.add_argument("-t", help="progress update", action="store")
args = parser.parse_args()

path_torrent_file = args.torrent_file
verbose = args.verbose

save_directory = args.directory
logging_time = int(args.t) if args.t else 30

signal.signal(signal.SIGINT, signal_handler)

if not os.path.exists(save_directory) or (not os.path.isdir(save_directory)):
	print("No such directory")
	exit()

if save_directory == "/":
	save_directory = os.getcwd()


my_ordred_dict = bencodepy.decode_from_file(path_torrent_file)
dict_hash = utils.compute_hash(bencodepy.encode(my_ordred_dict[b'info']))
my_peer_id = utils.random_peer_id()

hashes = my_ordred_dict[b'info'][b'pieces']

root_directory = ""
files = []
file = ()


if b'files' in my_ordred_dict[b'info'].keys():
	root_directory = str(my_ordred_dict[b'info'][b'name'], 'utf-8')
	if root_directory.endswith("/"): root_directory = root_directory[:-1]
	# if save_directory.endswith("/"): save_directory = save_directory[:-1]
	if not os.path.exists(save_directory + "/" + root_directory):
		os.mkdir(save_directory + "/" + root_directory)

	
	path = save_directory + "/" + root_directory + "/"
	for cur in my_ordred_dict[b'info'][b'files']:
		size = int(cur[b'length'])
		full_path = path + "".join(trace.decode() + "/"  for trace in cur[b'path'])
		files.append((size, full_path[:-1]))	
		for trace_i in range(len(cur[b'path']) - 1):
			dir_path = path + cur[b'path'][trace_i].decode()
			if not os.path.exists(dir_path):
				os.mkdir(dir_path)
			else:	
				dir_path += "/"
		if not os.path.exists(full_path[:-1]):
			open(full_path[:-1],  "w+b")		

	MULTI_FILE = True
else:
	file = str(my_ordred_dict[b'info'][b'name'], 'utf-8')
	if not os.path.exists(save_directory + "/" + file):
		open(save_directory + "/" + file, "w+b")
	MULTI_FILE = False



pieces = [hashes[i:i+20] for i in range(0, len(hashes), 20)]
downloaded_pieces = [0] * len(pieces)
check_partial_torrent()
print("{} number of pieces out of {} has been already downloaded".format(sum(downloaded_pieces), len(downloaded_pieces)))
full_length = 0
if b'length' in my_ordred_dict[b'info'].keys():
	full_length = my_ordred_dict[b'info'][b'length']
else:
	for file in my_ordred_dict[b'info'][b'files']:
		full_length += file[b'length']	


downloaded_bytes = sum(downloaded_pieces) *  my_ordred_dict[b'info'][b'piece length']
connected_peers = []
lock = threading.Lock()
pieces_lock = threading.Lock()
thread_i = 0
leachers = 0
threading.Thread(target = log_info, args=(), daemon = True).start()
threading.Thread(target = download,  daemon = True).start()

import seeding
seeding_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
seeding_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
	seeding_socket.bind(('',MY_PORT))
	seeding_socket.listen(5)
	print ('---' + "seeding" + "---") 	
except:
	print("Can't listen to this port(Somebody already listens , Sorry)")
	sys.exit()

while True:
	try:
		conn_socket, addr = seeding_socket.accept()
	except KeyboardInterrupt:
		break

	leachers += 1
	print("connected " + str(addr))
	if MULTI_FILE:
		arg = (dict_hash, my_peer_id, downloaded_pieces, files, full_length, MULTI_FILE,
		 my_ordred_dict[b'info'][b'piece length'] )

	else:
		path = save_directory + "/" + file
		arg = (dict_hash, my_peer_id, downloaded_pieces, path, full_length, MULTI_FILE,
			my_ordred_dict[b'info'][b'piece length'] )
	threading.Thread(target=seeding.serve_peer, args=(conn_socket, addr, arg) , daemon = True).start()
	

