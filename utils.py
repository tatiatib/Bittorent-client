import hashlib
import struct 
import socket
import bitstring
MY_PORT = 6969
TRANSACTION_ID = 123
PROTOCOL_ID = 0x41727101980


def random_peer_id():
	from random import choice
	from string import digits
	return ''.join(choice(digits) for _ in range(20))

def compute_hash(info):
	return hashlib.sha1(info).digest()


def get_handshake(info_hash, id):
	protocol_name = b'BitTorrent protocol'
	data = struct.pack('!B', len(protocol_name))
	data += protocol_name
	data += struct.pack('!Q', 0)
	data += info_hash
	data += bytes(id, 'ascii')

	return data

def get_announce_request(con_id, info_hash, peer_id, length):
	request = b''
	request += struct.pack('!Q', con_id) + struct.pack('!I', 1) + struct.pack('!I', TRANSACTION_ID)
	request += struct.pack('!20s', info_hash) + struct.pack('!20s', bytes(peer_id, 'ascii'))
	request += struct.pack('!Q', 0) + struct.pack('!Q', length) + struct.pack('!Q', 0)

	request += struct.pack('!I', 2) + struct.pack('!I', 0) + struct.pack('!I', 1010) + struct.pack('!i', -1)
	request += struct.pack('!H', MY_PORT) 
	return request

def get_connect_request():
	action = 0x0
	request = b''
	request += struct.pack('!q', PROTOCOL_ID) + struct.pack('!i', action) +  struct.pack('!i', TRANSACTION_ID)
	return request

def get_address(response):

	action, tr_id, interval, leechers, seeders = struct.unpack('!IIIII', response[:20])
	if action != 1:
		return None, None
	
	return socket.inet_ntoa(response[20:24]), struct.unpack('!H', (response[24:26]))[0]


def decode_peers(peers):
	peers = [peers[i:i+6] for i in range(0, len(peers), 6)]
	return [(socket.inet_ntoa(p[:4]), struct.unpack('!H', (p[4:]))[0]) for p in peers]


def get_bitfield_data(raw_data):
	return map(lambda x: int(x), list(bitstring.BitArray(raw_data[1:]).bin))

def set_have(raw_data, bitfield):
	piece_numb = struct.unpack('!I', raw_data[1:])[0]
	# while len(bitfield) < piece_numb:
		# bitfield.append(0)
	bitfield[piece_numb] = 1

def send_interested(peer_socket):
	data = struct.pack('!I', 1)  + struct.pack('!B', 2)
	peer_socket.sendall(data)


def interested(bitfield, downloaded_pieces):
	for i in range(len(downloaded_pieces)):
		bit = bitfield[i] - downloaded_pieces[i]
		bitfield[i] = bit if bit > 0 else 0

	if sum(bitfield) > 0:
		return True
	else:
		return False

def send_not_interested (peer_socket):
	data = struct.pack('!I', 1)  + struct.pack('!B', 3)
	peer_socket.sendall(data)

def send_piece_numb(peer_socket, index, length, begin = 0):
	data = struct.pack('!BIII', 6, index, begin, length)
	data_s = struct.pack('!I', len(data)) + data
	peer_socket.sendall(data_s) 


def get_unchoke():
	data = struct.pack("!I", 1) + struct.pack("!B", 1)
	return data 

def get_piece_packet(index, begin, piece):
	data = struct.pack('!BII', 7, index, begin)
	data += piece
	return struct.pack('!I', len(data)) + data

