# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial unified MCP server combining official `platform.higgsfield.ai` API and opt-in `cloud.higgsfield.ai` web backend.
- Model registry covering 27 image and video models (8 official, 4 web image, 15 web video).
- MCP tools: `list_models`, `generate_image`, `generate_video`, `get_status`, `cancel_job`, `upload_image`, `subscribe`.
- Two-tier authentication: `HIGGSFIELD_API_KEY` + `HIGGSFIELD_SECRET` for the official backend; Clerk JWT (auto-refresh / manual) for the opt-in web backend.
