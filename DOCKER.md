# Docker Deployment Guide for MeshCore Bot

This guide covers deploying the MeshCore Bot using Docker and Docker Compose.

## Prerequisites

- **Docker** 20.10.0 or higher
- **Docker Compose** 1.29.0 or higher (or Docker with Compose V2)
- **Meshtastic device** (for serial/BLE) or network access to a Meshtastic node (for TCP)
- **Configuration file** (`config.ini`)

## Quick Start

### 1. Prepare Configuration

Copy the example configuration and customize it:

```bash
cp config.ini.example config.ini
nano config.ini
```

**Key settings to configure:**
- `[Connection]` section: Set your connection type and device/host
- `[Bot]` section: Set bot name, location, timezone
- `[External_Data]` section: Add API keys if using weather, AQI, satellite features

### 2. Create Data Directory

```bash
mkdir -p data
```

### 3. Build and Start

```bash
# Build the Docker image
docker-compose build

# Start the bot
docker-compose up -d

# Check logs
docker-compose logs -f meshcore-bot
```

## Connection Type Configuration

### Serial Connection (USB)

**Default configuration in `docker-compose.yml`**

1. Identify your serial port:
   ```bash
   ls /dev/tty* | grep -E "(USB|ACM)"
   ```

2. Update `config.ini`:
   ```ini
   [Connection]
   connection_type = serial
   serial_port = /dev/ttyACM0
   ```

3. Update device mapping in `docker-compose.yml` if your device is different:
   ```yaml
   devices:
     - /dev/ttyUSB0:/dev/ttyUSB0  # Adjust as needed
   ```

4. **Permissions**: Ensure the container user has access to the device:
   ```bash
   # Option 1: Add your user to dialout group
   sudo usermod -aG dialout $USER
   
   # Option 2: Set device permissions
   sudo chmod 666 /dev/ttyACM0
   ```

### TCP Connection

**No device passthrough needed**

1. Update `config.ini`:
   ```ini
   [Connection]
   connection_type = tcp
   hostname = 192.168.1.60
   tcp_port = 5000
   ```

2. Create `docker-compose.override.yml`:
   ```yaml
   version: '3.8'
   services:
     meshcore-bot:
       devices: []  # Remove device mapping
   ```

### BLE Connection

**Requires host network mode**

1. Update `config.ini`:
   ```ini
   [Connection]
   connection_type = ble
   ble_device_name = MeshCore
   ```

2. Create `docker-compose.override.yml`:
   ```yaml
   version: '3.8'
   services:
     meshcore-bot:
       network_mode: host
       devices: []
   ```

3. Ensure Bluetooth is enabled on host:
   ```bash
   sudo systemctl status bluetooth
   ```

## Volume Management

### Persistent Data

The following directories are mounted as volumes:

- **`./config.ini`** → Configuration file (read-only)
- **`./data`** → SQLite databases and persistent data
- **`./translations`** → Localization files (read-only)
- **`meshcore-logs`** → Named volume for logs

### Backup Data

```bash
# Backup databases
docker-compose down
tar -czf meshcore-backup-$(date +%Y%m%d).tar.gz data/

# Restore from backup
tar -xzf meshcore-backup-20251208.tar.gz
docker-compose up -d
```

## Web Viewer

If enabled in `config.ini`:

```ini
[Web_Viewer]
enabled = true
host = 0.0.0.0
port = 8080
```

Access at: **http://localhost:8080**

To use a different port on the host:
```yaml
# In docker-compose.override.yml
services:
  meshcore-bot:
    ports:
      - "8888:8080"  # Access at http://localhost:8888
```

## Container Management

### View Logs

```bash
# Follow logs in real-time
docker-compose logs -f meshcore-bot

# View last 100 lines
docker-compose logs --tail=100 meshcore-bot

# View logs with timestamps
docker-compose logs -t meshcore-bot
```

### Restart Bot

```bash
# Restart
docker-compose restart meshcore-bot

# Stop
docker-compose stop meshcore-bot

# Start
docker-compose start meshcore-bot

# Recreate container
docker-compose up -d --force-recreate meshcore-bot
```

### Update Configuration

```bash
# Edit config
nano config.ini

# Restart to apply changes
docker-compose restart meshcore-bot
```

### Update Bot Code

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

## Troubleshooting

### Device Not Found

**Error**: `Could not open port /dev/ttyACM0`

**Solutions**:
1. Verify device exists: `ls -l /dev/ttyACM0`
2. Check permissions: `ls -l /dev/ttyACM0`
3. Add to dialout group: `sudo usermod -aG dialout $USER` (logout/login required)
4. Try privileged mode (temporary test):
   ```yaml
   services:
     meshcore-bot:
       privileged: true
   ```

### BLE Connection Issues

**Error**: `Failed to discover BLE device`

**Solutions**:
1. Ensure host network mode: `network_mode: host`
2. Check Bluetooth service: `sudo systemctl status bluetooth`
3. Verify device is discoverable
4. Install bluez: `sudo apt-get install bluez`

### Permission Denied Errors

**Error**: `PermissionError: [Errno 13] Permission denied`

**Solutions**:
1. Check volume permissions:
   ```bash
   sudo chown -R 1000:1000 data/
   ```
2. Match container user to host user in `docker-compose.yml`:
   ```yaml
   user: "1000:1000"  # Use your UID:GID
   ```

### Web Viewer Not Accessible

**Error**: Cannot access `http://localhost:8080`

**Solutions**:
1. Verify config: `enabled = true` in `[Web_Viewer]`
2. Check port mapping in `docker-compose.yml`
3. View logs: `docker-compose logs -f meshcore-bot`
4. Check firewall rules

### Container Keeps Restarting

**Error**: Container in restart loop

**Solutions**:
1. Check logs: `docker-compose logs meshcore-bot`
2. Verify `config.ini` exists and is valid
3. Check device connectivity
4. Review Python errors in logs

## Migration from Systemd Service

### 1. Stop the Systemd Service

```bash
sudo systemctl stop meshcore-bot
sudo systemctl disable meshcore-bot
```

### 2. Copy Configuration

```bash
# If installed via install-service.sh
sudo cp /opt/meshcore-bot/config.ini ./config.ini

# Copy databases if they exist
sudo cp /opt/meshcore-bot/*.db ./data/
sudo chown -R $USER:$USER ./data/
```

### 3. Start Docker Container

```bash
docker-compose up -d
```

### 4. Verify Migration

```bash
# Check logs
docker-compose logs -f meshcore-bot

# Verify databases loaded
ls -l data/
```

## Advanced Configuration

### Custom Network

```yaml
# docker-compose.override.yml
services:
  meshcore-bot:
    networks:
      - meshcore-network

networks:
  meshcore-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

### Resource Limits

```yaml
# docker-compose.override.yml
services:
  meshcore-bot:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          memory: 256M
```

### Multiple Instances

To run multiple bots with different devices:

```bash
# Create separate directories
mkdir meshcore-bot-1 meshcore-bot-2

# Copy files
cp docker-compose.yml config.ini meshcore-bot-1/
cp docker-compose.yml config.ini meshcore-bot-2/

# Edit configs with different ports/devices
cd meshcore-bot-1
# Edit config.ini and docker-compose.yml
docker-compose up -d

cd ../meshcore-bot-2
# Edit config.ini and docker-compose.yml
docker-compose up -d
```

## Security Notes

- **Privileged mode**: Avoid using `privileged: true` in production. Use specific device mapping instead.
- **API keys**: Keep `config.ini` secure and never commit it to version control.
- **User permissions**: Run container as non-root user (default: uid 1000).
- **Network exposure**: Web viewer on `0.0.0.0` exposes it to your network. Use `127.0.0.1` for localhost-only access.

## Support

For issues or questions:
- Check container logs: `docker-compose logs -f`
- Review main README.md for bot-specific help
- Check GitHub issues

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [MeshCore Documentation](https://github.com/meshcore-dev/MeshCore)
