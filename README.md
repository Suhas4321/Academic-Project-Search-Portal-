
# Project Search Portal

A comprehensive full-stack web application designed for academic institutions to search, manage, and explore student projects across multiple academic years. This portal provides powerful search capabilities, administrative tools, and a responsive user interface for efficient project discovery and management.

## 🚀 Overview

The Project Search Portal is built to solve the challenge of finding and managing academic projects across different years and departments. It features advanced full-text search capabilities, real-time suggestions, and comprehensive project management tools that make it easy for students, faculty, and administrators to discover relevant projects.

## ✨ Key Features

### 🔍 Advanced Search System
- **Full-Text Search**: Powered by PostgreSQL's tsvector and tsquery with weighted field ranking
- **Multi-Year Search**: Search across all academic years or filter by specific years
- **Search Types**: 
  - All fields search (default)
  - Project title specific search
  - Guide/mentor name specific search
- **Real-time Suggestions**: Dynamic search suggestions as you type
- **Ranking Algorithm**: Results ranked by relevance using ts_rank scoring

### 📊 Project Management
- **Multi-Year Support**: Organize projects by academic year (2021-22, 2022-23, etc.)
- **Comprehensive Project Data**: 
  - Group information and USN numbers
  - Student names and project titles
  - Guide/mentor details
  - Project outcomes and proof links
  - PowerPoint and report links
- **Excel Import**: Bulk import projects from Excel files with intelligent data cleaning
- **CRUD Operations**: Full create, read, update, delete functionality for project records

### 🛡️ Administrative Interface
- **Secure Admin Panel**: Password-protected administrative access
- **Table Management**: View and manage different academic year tables
- **Data Import**: Upload and process Excel files with automatic column mapping
- **Real-time Updates**: Immediate reflection of changes in search results

### 🎨 User Experience
- **Responsive Design**: Mobile-first design that works on all devices
- **Modern UI**: Clean, intuitive interface built with Tailwind CSS and shadcn/ui
- **Fast Performance**: Optimized with GIN indexing and async operations
- **Error Handling**: Graceful error handling with user-friendly messages

## 🛠️ Technology Stack

### Backend
- **Python 3.9+**: Core programming language
- **FastAPI**: Modern, fast web framework for building APIs
- **SQLAlchemy 2.0**: Modern Python SQL toolkit with async support
- **PostgreSQL 15**: Advanced relational database with full-text search
- **asyncpg**: High-performance async PostgreSQL driver
- **Pandas**: Data manipulation and Excel processing
- **Uvicorn**: Lightning-fast ASGI server

### Frontend
- **React 18**: Modern JavaScript library for building user interfaces
- **TypeScript**: Type-safe JavaScript development
- **Vite**: Next-generation frontend build tool
- **Tailwind CSS**: Utility-first CSS framework
- **shadcn/ui**: High-quality React component library
- **React Query (TanStack)**: Powerful data fetching and state management
- **React Router DOM**: Declarative routing for React applications

### Database & Search
- **PostgreSQL Full-Text Search**: Advanced search with tsvector and tsquery
- **GIN Indexing**: Optimized indexing for fast full-text search
- **Weighted Search Vectors**: Project titles weighted higher than other fields
- **Multi-table Search**: Seamless searching across multiple academic year tables

### Development & Deployment
- **Docker & Docker Compose**: Containerized deployment
- **Hot Reload**: Development server with instant updates
- **Environment Configuration**: Flexible configuration management
- **Automated Setup Scripts**: One-click deployment for college environments

## 🏗️ Architecture

### Database Design
```
Academic Year Tables (2021_22, 2022_23, 2023_24, 2024_25, etc.)
├── group_no (Primary Key)
├── usn (Student IDs)
├── name (Student Names)
├── project_title (Weighted A in search)
├── guide_name (Weighted B in search)
├── outcomes
├── proof_link
├── ppt_links
├── report_links
└── search_vector (Generated tsvector for full-text search)
```

### API Architecture
```
FastAPI Application
├── /api/search/ (Full-text search endpoints)
├── /api/suggestions/ (Real-time search suggestions)
├── /api/years (Available academic years)
└── /admin/ (Administrative operations)
    ├── /login (Admin authentication)
    ├── /tables (Table management)
    ├── /upload-excel (Excel import)
    └── CRUD operations
```

## 🚀 Getting Started

### Prerequisites
- Docker and Docker Compose
- Git (for cloning the repository)

### Quick Start (Recommended)
1. **Clone the repository**
   ```bash
   git clone <your-repository-url>
   cd project-search-portal
   ```

2. **Run the setup script**
   ```bash
   chmod +x setup-college.sh
   ./setup-college.sh
   ```

3. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs
   - Admin Panel: Use credentials from setup

### Manual Installation
1. **Environment Setup**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Start Services**
   ```bash
   docker-compose up --build -d
   ```

3. **Import Your Data**
   - Access admin panel
   - Upload Excel files with project data
   - System automatically processes and indexes the data

## 📊 Features Deep Dive

### Search Algorithm
The search system uses PostgreSQL's advanced full-text search capabilities:
- **Weighted Vectors**: Project titles receive higher weight (A) than guide names (B)
- **Ranking**: Results sorted by relevance score using ts_rank
- **Multi-table**: Searches across all academic years simultaneously
- **Performance**: GIN indexes ensure sub-second search times

### Data Processing
The Excel import system features:
- **Intelligent Column Mapping**: Automatically detects column headers
- **Data Cleaning**: Handles merged cells, empty rows, and inconsistent formatting
- **Validation**: Ensures data integrity before database insertion
- **Batch Processing**: Efficiently processes large datasets

### Error Handling
- **Graceful Degradation**: Missing columns in older tables don't break functionality
- **Transaction Safety**: Database operations are atomic and rollback on errors
- **User Feedback**: Clear error messages and success notifications

## 🔧 Configuration

### Environment Variables
```bash
# Database Configuration
ASYNC_DB_URL=postgresql+asyncpg://user:password@host:port/database
SYNC_DB_URL=postgresql://user:password@host:port/database

# Admin Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password
```

### Database Schema
The system automatically creates and manages database tables for each academic year, with full-text search vectors and optimized indexes.

## 📈 Performance Optimizations

- **Async Operations**: All database operations use async/await patterns
- **Connection Pooling**: Efficient database connection management
- **GIN Indexing**: Optimized full-text search performance
- **Lazy Loading**: Components and data loaded on demand
- **Caching**: Search suggestions cached for better UX

## 🛡️ Security Features

- **Admin Authentication**: Secure login system for administrative access
- **Input Validation**: All user inputs validated and sanitized
- **SQL Injection Prevention**: Parameterized queries throughout
- **Environment Variables**: Sensitive data stored in environment configuration

## 📱 Responsive Design

The application is fully responsive and works seamlessly across:
- Desktop computers
- Tablets
- Mobile phones
- Various screen sizes and orientations

## 🤝 Contributing

This project was developed as an academic portal solution. For contributions:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

This project is developed for educational purposes and institutional use.

## 🙏 Acknowledgments

- Built for academic institutions to enhance project discovery
- Utilizes modern web technologies for optimal performance
- Designed with user experience and scalability in mind

---

**Developed with ❤️ for academic excellence and efficient project management.**
