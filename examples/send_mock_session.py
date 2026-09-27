"""Send a short synthetic session to the loopback mock host (no hardware)."""
import json
import socket
import time


def main():
    with socket.create_connection(('127.0.0.1', 8765), timeout=2) as connection:
        reader = connection.makefile('rb')
        for index in range(35):
            # First release, then anchor, move slightly, and finish released.
            packet = {
                'type': 'teleop_pose',
                'timestamp': time.time(),
                'position': [min(max(index - 1, 0), 30) * 0.0005, 0.0, 0.0],
                'quaternion': [0.0, 0.0, 0.0, 1.0],
                'gripper': 0.8,
                'clutch_engaged': 1 <= index < 33,
                'recording': 0 < index < 34,
            }
            connection.sendall((json.dumps(packet) + '\n').encode())
            response = reader.readline(65536)
            if not response:
                raise RuntimeError('Host closed the connection')
            ack = json.loads(response)
            if ack.get('status') not in ('ok', 'held'):
                raise RuntimeError(f'Host rejected the sample: {ack}')
            time.sleep(0.02)
        connection.sendall(b'{"type":"stop"}\n')
        print(json.loads(reader.readline(65536)))
    print('Synthetic session complete. Inspect teleop_dataset for local JSON output.')


if __name__ == '__main__':
    main()
