# Windows Client Tool

A comprehensive Windows 11 optimization and system diagnostics utility with a modern Qt6-based graphical interface.

## Features

### System Analysis & Optimization
- **Dashboard**: Live monitoring of CPU, memory, disk, network usage
- **Event Viewer**: Parse Windows Event logs (System, Application, Security)
- **CBS/DISM Logs**: Analyze component store and system repair logs
- **Windows Update**: Check and install pending updates
- **Process Explorer**: View running processes with resource usage
- **Performance Tuner**: Identify and fix performance bottlenecks
- **Cleanup Scanner**: Find and remove unnecessary files

### System Information
- **Hardware Inventory**: Collect detailed hardware specifications
- **Driver Manager**: View and manage installed drivers
- **Windows Features**: Enable/disable optional Windows features
- **Network Diagnostics**: Analyze network adapter status and issues
- **Security Dashboard**: Review security settings and vulnerabilities
- **Certificates**: View and manage system certificates
- **Power Settings**: Adjust power and boot optimization options

### Tools
- **Registry Explorer**: Browse and edit registry keys (backup-first)
- **Environment Variables**: View and edit system variables
- **Startup Manager**: Control startup programs and services
- **Scheduled Tasks**: Manage task scheduler jobs
- **Shared Folders**: Manage network shares
- **WiFi Analyzer**: Diagnose wireless network issues
- **Remote Tools**: Remote desktop and command line utilities

### Utilities
- **Tweaks**: Apply system optimization recommendations
- **Backup Service**: Config file backup and restore
- **System Report**: Generate comprehensive system health reports

## Requirements

- Windows 10/11 (64-bit)
- Python 3.12+
- PyQt6
- psutil

## Installation

1. Clone or download this repository
2. Create a virtual environment:
   `ash
   python -m venv venv
   venv\Scripts\activate
   `
3. Install dependencies:
   `ash
   pip install -r requirements.txt
   `
4. Run the application:
   `ash
   python src/main.py
   `

## Building an Executable

`ash
pyinstaller --clean WinClientTool.spec
`

The resulting executable will be located in uild/WinClientTool/

## Configuration

The application stores settings in %APPDATA%\WindowsTweaker\config.json:
- Theme (dark/light)
- Log level (DEBUG/INFO/WARNING/ERROR)
- Window size and position
- Start minimized preferences

## License

MIT License - See [LICENSE](LICENSE) for details

## Author

Auto-generated tool for Windows 11 system optimization

## Contributing

This is a system optimization tool. Contributions should focus on:
- Bug fixes
- Performance improvements
- Security hardening
- Documentation enhancements

## Roadmap

- [x] Core modules implementation
- [ ] Full AI-powered recommendations (Ollama integration)
- [ ] Enhanced restore manager
- [ ] Additional diagnostic modules
- [ ] Plugin system for custom analysis tools

## Support

For issues or questions, create an issue in the repository.
