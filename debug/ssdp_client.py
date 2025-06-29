"""
SSDP Debug Tool which listens for SSDP packets on the network.
Prints the details of the SSDP packets received.

"""

import socket
import threading
import time
import struct

HEADERS_TO_IGNORE = [ # Generally uninteresting headers
    'NT', 'NTS', 'ST'
]

class SSDPClient:
    def __init__(self, multicast_group='239.255.255.250', multicast_port=1900, interface_ip='0.0.0.0'):
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.interface_ip = interface_ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # Allow multiple bindings
        self.sock.bind((self.interface_ip, self.multicast_port))

        # Join the multicast group
        mreq = struct.pack("4sl", socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self.running = True
        self.thread = threading.Thread(target=self.listen)
        self.thread.start()

    def listen(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.handle_ssdp_packet(data, addr)
            except Exception as e:
                print(f"Error receiving SSDP packet: {e}")

    def handle_ssdp_packet(self, data, addr):
        try:
            decoded_data = data.decode('utf-8')
            print(f"\nReceived SSDP packet from {addr[0]}:{addr[1]}:")
            print("----------------------------------------")
            for line in decoded_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                if any(header in line for header in HEADERS_TO_IGNORE):
                    continue
                print(line)
            print("----------------------------------------")
        except UnicodeDecodeError:
            print(f"\nReceived SSDP packet from {addr[0]}:{addr[1]} (unable to decode):")
            print(data)

    def stop(self):
        self.running = False
        self.sock.close()
        self.thread.join()

def main():
    ssdp_client = SSDPClient()
    try:
        print("Listening for SSDP packets...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping SSDP client...")
        ssdp_client.stop()

if __name__ == "__main__":
    main()
else:
    print("This script is intended to be run directly, not imported as a module.")
    print("Run it using: python ssdp_client.py")
    exit(1)