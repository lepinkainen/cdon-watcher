# CDON Watcher Documentation

Welcome to the comprehensive documentation for CDON Watcher, a price tracking system for Blu-ray and 4K Blu-ray movies on CDON.fi.

## Documentation Structure

This documentation is organized into focused guides, each covering specific aspects of the project:

### 📋 Getting Started

| Document                             | Description                                  |
| ------------------------------------ | -------------------------------------------- |
| [**01_overview.md**](01_overview.md) | Project overview, features, and architecture |
| [**02_setup.md**](02_setup.md)       | Installation and setup instructions          |
| [**03_usage.md**](03_usage.md)       | Usage guide for CLI and web interface        |

### 🔧 Technical Reference

| Document                                           | Description                                     |
| -------------------------------------------------- | ----------------------------------------------- |
| [**04_api_reference.md**](04_api_reference.md)     | Complete API documentation with examples        |
| [**05_database_schema.md**](05_database_schema.md) | Database models, relationships, and queries     |
| [**06_configuration.md**](06_configuration.md)     | Configuration options and environment variables |

### 👥 Development & Support

| Document                                           | Description                                     |
| -------------------------------------------------- | ----------------------------------------------- |
| [**07_development.md**](07_development.md)         | Development guidelines and contribution process |
| [**08_troubleshooting.md**](08_troubleshooting.md) | Common issues and solutions                     |

## Quick Start

If you're new to CDON Watcher, follow this recommended reading order:

1. **[Overview](01_overview.md)** - Understand what CDON Watcher does
2. **[Setup](02_setup.md)** - Get the system running
3. **[Usage](03_usage.md)** - Learn how to use the features

## Key Topics

### For Users

- **Price Monitoring**: Track Blu-ray and 4K Blu-ray prices
- **Watchlist Management**: Set target prices and get alerts
- **Web Dashboard**: User-friendly interface for monitoring
- **Notifications**: Email and Discord alert configuration

### For Developers

- **API Integration**: RESTful API for custom integrations
- **Database Design**: SQLModel with SQLite backend
- **Scraping Architecture**: Hybrid Playwright + BeautifulSoup approach
- **Testing Strategy**: Unit and integration test patterns

### For Administrators

- **Configuration Management**: Environment variables and settings
- **Performance Tuning**: Optimization and monitoring
- **Troubleshooting**: Common issues and solutions
- **Security**: Best practices and considerations

## Additional Resources

### External Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/) - Web framework
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/) - Database ORM
- [Playwright Documentation](https://playwright.dev/python/docs/intro) - Browser automation
- [Python Documentation](https://docs.python.org/3/) - Language reference

### Project Files

- [`README.md`](../README.md) - Main project README
- [`CLAUDE.md`](../CLAUDE.md) - AI assistant guidelines
- [`pyproject.toml`](../pyproject.toml) - Project configuration
- [`docker-compose.yml`](../docker-compose.yml) - Container orchestration

## Support

### Getting Help

1. **Check this documentation first** - Most questions are answered here
2. **Search existing issues** - Check GitHub Issues for similar problems
3. **Create a new issue** - For bugs or feature requests
4. **Community discussions** - For questions and general help

### Issue Reporting

When reporting issues, please include:

- **System information**: OS, Python version, container runtime
- **Steps to reproduce**: Exact commands and expected behavior
- **Error logs**: Relevant log output
- **Configuration**: Sanitized configuration details

## Contributing

We welcome contributions! See the [Development Guide](07_development.md) for:

- Code style guidelines
- Testing requirements
- Pull request process
- Development environment setup

## License

This documentation is part of the CDON Watcher project, which is licensed under the MIT License. See the main project [`LICENSE`](../LICENSE) file for details.

---

**Last Updated**: August 31, 2025
**Version**: 1.0.0
**Project**: [CDON Watcher](https://github.com/lepinkainen/cdon-watcher)
