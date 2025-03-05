import http.server
import socketserver
import os
import socket

def find_free_port(start_port=8000, max_attempts=100):
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return None

def run_simple_server(port=8000):
    """Run a simple HTTP server on the specified port."""
    # Find an available port if the specified one is in use
    if port is None:
        port = find_free_port()
    
    handler = http.server.SimpleHTTPRequestHandler
    
    try:
        httpd = socketserver.TCPServer(("", port), handler)
    except OSError:
        print(f"Port {port} is in use. Finding an available port...")
        port = find_free_port()
        httpd = socketserver.TCPServer(("", port), handler)
    
    print(f"Server running at http://localhost:{port}/")
    print("To access the recaptcha page, go to: http://localhost:{port}/recaptcha_simulation.html")
    print("Press Ctrl+C to stop the server")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
        httpd.server_close()

if __name__ == "__main__":
    run_simple_server() 