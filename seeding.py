import struct
import utils
import socket
import os


SIZE = 0
MULTI = 0
PATH = ''
UPLOADED = 0
PIECE_LENGTH = 0
FILES = []

def parse_data_handshake(data):
	length = struct.unpack('!B', data[:1])[0]
	if length > 0:
		protocol_name = data[1:length + 1]
		if protocol_name == b'BitTorrent protocol':
			data = data[length+1:]
			if data:
				zeros = struct.unpack('!Q', data[:8])[0]
				data = data[8:]
				if len(data) > 20:
					return data[:20]
		
	return ''

	
def send_bitfield(peer_socket, downloaded_pieces):
	msg = struct.pack('!B', 5)

	string_bits = ""
	for bit in downloaded_pieces:
		string_bits += '0' if bit == 0 else '1'

	while not len(string_bits) % 8 == 0:
		string_bits += '0'

	res = b''
	index = 0
	while index < len(string_bits):
		next_byte = string_bits[index: index + 8]
		res += int.to_bytes(int(next_byte, 2), 1, byteorder='big')
		index += 8

	msg += res
	raw_msg =  struct.pack( '!I', len(msg)) +  msg
	peer_socket.sendall(raw_msg)

	

def serve_peer(peer_socket, peer_address, infos):
	dict_hash, my_peer_id, downloaded_pieces, path, length, multi, piece = infos
	global SIZE
	SIZE = length
	global MULTI
	MULTI = multi

	if MULTI:
		global FILES
		FILES = path
	else:
		global PATH
		PATH = path

	global PIECE_LENGTH
	PIECE_LENGTH = piece


	data = peer_socket.recv(1024)
	peer_socket.settimeout(5)
	request_info = parse_data_handshake(data)
	if request_info and request_info == dict_hash:
		handshake = utils.get_handshake(dict_hash, my_peer_id)
		peer_socket.sendall(handshake)
		peer_socket.settimeout(None)
		send_bitfield(peer_socket, downloaded_pieces)
		get_requests(peer_socket, infos)

	else:
		peer_socket.close()
		

def process_request(data, peer_socket):
	index, begin, length = struct.unpack('!III', data)

	begin_ = begin
	global UPLOADED
	data = b''
	if MULTI:
		begin = index * PIECE_LENGTH + begin
		for file_size, file in FILES:
			if file_size < begin:
				begin -= file_size
			else:
				with open(file, "r+b") as cur_file:
					if begin + length < file_size:
						cur_file.seek(begin)
						data += cur_file.read(length)
						break
					else:
						cur_file.seek(begin)
						data_cur = cur_file.read()
						length -= len(data_cur)
						data += data_cur
						begin = 0



	else:		
		if os.path.exists(PATH):	
			with open(PATH, "r+b") as cur_file:
				begin = index * PIECE_LENGTH + begin
				if SIZE - UPLOADED > 0:
					cur_file.seek(begin)
					data = cur_file.read(length)
					# else:
					# 	data = cur_file.read()


	
	piece_packet = utils.get_piece_packet(index, begin, data)
	peer_socket.sendall(piece_packet)
	# peer_socket.settimeout(4)
	
	UPLOADED += length


def process_data(peer_socket, infos, data):
	try:
		if 2 == struct.unpack('!B', data[:1])[0]:
			unchoke_msg = utils.get_unchoke()
			peer_socket.sendall(unchoke_msg)
			return False

		if 3 == struct.unpack('!B', data[:1])[0]:
			return True

		if 1 == struct.unpack('!B', data[:1])[0]:
			return False


		if 6 == struct.unpack('!B', data[:1])[0]:			
			process_request(data[1:], peer_socket)
			return False
		#choke
		if 0 == struct.unpack('!B', data[:1])[0]:
			return True
		else:
			return False

	except socket.timeout:
		print("socket time out")
		return True

	

def get_requests(peer_socket, infos):
	peer_socket.settimeout(4)

	try:
		while True:	
			data = b''
			while len(data) < 4:
				new_data = peer_socket.recv(4 - len(data))
				if new_data == b'':
					continue
				data += new_data
				peer_socket.settimeout(4)

			msg_length = struct.unpack('!I', data)[0]

			if msg_length == 0:
				continue
			data = b''
			while msg_length > 0:
				raw_data = peer_socket.recv(msg_length)
				if raw_data == b'': 
					break
				peer_socket.settimeout(4)
				data += raw_data
				msg_length -= len(raw_data) 

			peer_socket.settimeout(None)
			if process_data(peer_socket, infos, data):
				peer_socket.close()
				break

	except(socket.timeout):
		peer_socket.close()