# CLAUDE.md - AI Assistant Guide

## 📋 Project Overview

**Entenda Aqui** (Understand Here) is a Flask-based web application that simplifies complex legal documents into plain language using Google Gemini AI. The application is designed to make legal documents accessible to everyday citizens in Brazil, with a strong focus on LGPD (Brazilian data protection law) compliance.

### Core Mission
Transform complex legal documents (court decisions, summons, rulings) into simple, understandable language with actionable insights, urgency indicators, and personalized explanations based on the user's role in the case.

---

## 🏗️ Architecture

### Tech Stack

**Backend:**
- **Python 3.11** - Primary language
- **Flask 3.0.3** - Web framework
- **Gunicorn 21.2.0** - WSGI production server
- **PyMuPDF 1.24.2** - PDF text extraction
- **Tesseract OCR** - Optical character recognition for scanned documents
- **Pillow 10.4.0** - Image processing
- **OpenCV (optional)** - Advanced image preprocessing
- **ReportLab 4.2.2** - PDF generation
- **SQLite** - Statistics storage (LGPD-compliant)

**AI/ML:**
- **Google Gemini API** - Natural language processing
- **Multi-model fallback system:**
  1. gemini-2.5-flash-lite (priority 1, fastest)
  2. gemini-2.5-flash (priority 2)
  3. gemini-2.0-flash-exp (priority 3, experimental)
  4. gemini-1.5-flash (priority 4, fallback)

**Frontend:**
- **Vanilla JavaScript** (ES6+)
- **HTML5/CSS3** with custom styling
- **No frameworks** - Direct DOM manipulation
- **Responsive design** - Mobile-first approach

**Infrastructure:**
- **Deployment**: Render.com (Free tier)
- **Region**: Oregon
- **Workers**: 2 Gunicorn workers
- **Timeout**: 120 seconds per request
- **Memory optimization**: Preloaded app, shared memory

---

## 📁 Project Structure

```
projeto-linguaguem-simples/
│
├── app.py                      # Main Flask application (117KB - comprehensive)
├── database.py                 # LGPD-compliant statistics tracking
├── gunicorn_config.py          # Production server configuration
├── requirements.txt            # Python dependencies
├── render.yaml                 # Render.com deployment config
├── install_tesseract.sh        # Tesseract installation script
├── Dockerfile.txt              # Docker configuration (reference)
├── .gitignore                  # Git ignore rules
├── .dockerignore               # Docker ignore rules
│
├── templates/
│   └── index.html              # Main frontend (131KB - comprehensive SPA)
│
├── static/
│   ├── style.css               # Additional styles
│   ├── avatar.js               # Avatar interactions
│   ├── logo.png                # INOVASSOL logo
│   ├── avatar.png              # Chat avatar
│   ├── vou-começar.mp3         # Audio feedback (starting)
│   └── prontinho-simplifiquei.mp3  # Audio feedback (completed)
│
├── stats.db                    # SQLite database (LGPD-compliant)
└── README.md                   # User-facing documentation
```

---

## 🔑 Key Components

### 1. **app.py** - Main Application (app.py:1-1200+)

The heart of the application with several critical subsystems:

#### Core Endpoints:
- `GET /` - Serve main interface
- `POST /processar` - Process uploaded documents
- `POST /chat` - Handle chat questions about processed documents
- `GET /download_pdf` - Download simplified PDF
- `GET /health` - Health check endpoint
- `GET /estatisticas` - Statistics endpoint

#### Critical Systems:

**Rate Limiting (app.py:99-102):**
- 10 requests per minute per IP
- Automatic cleanup thread
- Thread-safe with locks

**File Management (app.py:116-165):**
- Automatic registration of temporary files
- 30-minute expiration (TEMP_FILE_EXPIRATION)
- Background cleanup thread
- LGPD compliance - automatic deletion

**OCR Processing:**
- Tesseract OCR for scanned documents
- Image preprocessing with Pillow
- Optional OpenCV enhancement (if available)
- Language: Portuguese (por)

**AI Integration:**
- Multi-model Gemini fallback system
- Complexity-based model selection
- Usage statistics tracking
- Error handling and retry logic

### 2. **database.py** - Statistics System

**LGPD-Compliant Design:**
- Stores ONLY aggregate counters
- ZERO personal data or document content
- Automatic cleanup of old daily stats (30 days)
- Thread-safe operations with locks

**Key Functions:**
- `init_db()` - Initialize SQLite database
- `incrementar_documento(tipo)` - Increment counters (database.py:62)
- `get_estatisticas()` - Retrieve aggregated stats (database.py:105)
- `limpar_estatisticas_antigas()` - Cleanup old data (database.py:175)

**Statistics Tracked:**
- Total documents processed
- Documents processed today
- Count by document type (sentence, summons, ruling, etc.)
- Milestone progress (Bronze/Silver/Gold/Diamond)

### 3. **Frontend Architecture** (templates/index.html)

**Single-Page Application Features:**
- Drag-and-drop file upload
- User perspective modal (plaintiff/defendant)
- Real-time processing feedback
- Chat interface for questions
- Suggested questions
- Urgency indicators
- Download/copy/share functionality

**Key JavaScript Functions:**
- `handleFiles()` - Process file uploads
- `confirmarPerspectiva()` - User role selection
- `uploadFile()` - Send to backend
- `showResult()` - Display simplified content
- `toggleChat()` - Chat interface
- `sendMessage()` - Chat interactions

---

## 🔐 Environment Variables

Required environment variables:

```bash
GEMINI_API_KEY=your_gemini_api_key_here  # REQUIRED
SECRET_KEY=your_flask_secret_key         # Auto-generated if not set
PORT=8080                                # Default: 8080
FLASK_ENV=production                     # Default: production
```

**Getting Gemini API Key:**
1. Visit https://makersuite.google.com/app/apikey
2. Sign in with Google account
3. Create API key
4. Add to `.env` file or Render environment variables

---

## 🚀 Development Workflow

### Local Development

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Tesseract OCR
# Ubuntu/Debian:
sudo apt-get install tesseract-ocr tesseract-ocr-por
# macOS:
brew install tesseract tesseract-lang

# 4. Set environment variables
export GEMINI_API_KEY="your_key_here"
export SECRET_KEY="your_secret_here"

# 5. Run development server
python app.py
# Access: http://localhost:8080
```

### Production Deployment (Render)

**Automatic deployment via render.yaml:**
- Push to main branch triggers deployment
- Health check at `/health`
- Auto-scaling disabled (free tier)
- Environment variables via Render dashboard

**Manual deployment:**
```bash
# Ensure render.yaml is configured
git push origin main
# Render automatically builds and deploys
```

---

## 🎯 Key Conventions for AI Assistants

### 1. **LGPD Compliance - CRITICAL**

**Always maintain LGPD compliance:**
- ✅ Store only aggregate statistics
- ✅ Auto-delete temporary files (30 min)
- ✅ Auto-delete old statistics (30 days)
- ❌ NEVER store document content in database
- ❌ NEVER store user personal information
- ❌ NEVER log sensitive document data

**Before adding any data storage:**
1. Verify it's aggregate/anonymous data only
2. Implement automatic cleanup
3. Document the retention policy
4. Use thread-safe operations

### 2. **Code Style**

```python
# Follow existing patterns:

# Logging with emojis for visibility
logging.info("✅ Success message")
logging.warning("⚠️ Warning message")
logging.error("❌ Error message")

# Thread safety for shared resources
with cleanup_lock:
    # Critical section
    pass

# Portuguese comments for Brazilian context
# Comentários em português quando apropriado

# Type hints not used - maintain consistency
def funcao(parametro):
    """Docstring in Portuguese explaining function"""
    pass
```

### 3. **AI Model Management**

**Multi-model fallback (app.py:54-92):**
- Always try models in priority order
- Track usage statistics
- Log model successes/failures
- Update model list as Gemini releases new versions

**When adding new models:**
1. Add to GEMINI_MODELS list with priority
2. Update usage stats dictionary
3. Test fallback behavior
4. Document in comments

### 4. **Error Handling**

```python
# Graceful degradation pattern:
try:
    # Primary functionality
    result = use_advanced_feature()
except Exception as e:
    logging.warning(f"Fallback: {e}")
    # Fallback functionality
    result = use_basic_feature()
```

**Critical paths with multiple fallbacks:**
- OCR: OpenCV → Pillow basic → Raw Tesseract
- AI: Gemini 2.5 Lite → 2.5 Flash → 2.0 Exp → 1.5 Flash
- File processing: PyMuPDF → Image extraction → Error message

### 5. **Frontend Conventions**

**Vanilla JavaScript patterns:**
```javascript
// Event delegation
document.querySelectorAll('.elements').forEach(el => {
    el.addEventListener('click', handler);
});

// Direct DOM manipulation
document.getElementById('element').classList.add('show');

// Fetch API for AJAX
fetch('/endpoint', {
    method: 'POST',
    body: formData
}).then(response => response.json())
  .then(data => handleData(data));
```

**CSS naming:**
- Use kebab-case: `.result-section`, `.chat-container`
- Semantic class names
- Responsive breakpoints at 768px (mobile)
- CSS variables for theming (`:root`)

### 6. **Testing Strategy**

**When making changes:**
1. Test locally with sample PDF
2. Test with scanned document (OCR path)
3. Test rate limiting (10 requests)
4. Verify LGPD cleanup (check temp files)
5. Test all Gemini model fallbacks
6. Mobile responsive testing
7. Check logs for errors/warnings

**No automated tests exist** - manual testing is current practice

### 7. **Git Workflow**

```bash
# Feature branches with claude/ prefix
git checkout -b claude/feature-description-SESSION_ID

# Commit messages in Portuguese with clear intent
git commit -m "Adicionar funcionalidade X para resolver Y"

# Push to feature branch
git push -u origin claude/feature-description-SESSION_ID

# Create PR to main
gh pr create --title "Título" --body "Descrição"
```

**Branch naming convention:**
- Format: `claude/description-SESSION_ID`
- Example: `claude/deploy-critical-fixes-011CUzX2QY3TR6Vrwz64oiku`
- Always include session ID for tracking

### 8. **Performance Considerations**

**Memory constraints (Render Free Tier: 512MB):**
- Only 2 Gunicorn workers (gunicorn_config.py:8)
- Preload app to share memory
- Max request size: 10MB
- Request recycling after 100 requests
- Timeout: 120 seconds

**Optimization strategies:**
- Cache processed results (1 hour)
- Stream large files
- Cleanup temp files aggressively
- Use worker temp dir in RAM (/dev/shm)

### 9. **Security Practices**

**File upload validation:**
- Whitelist extensions only
- Max 10MB file size
- Secure filename handling (werkzeug.secure_filename)
- Temporary storage only
- Automatic cleanup

**API key management:**
- Never commit API keys
- Use environment variables
- Validate key presence at startup
- Log configuration status (without key)

### 10. **User Experience Priorities**

**Critical UX elements:**
1. **Urgency indicators** - Visual alerts for time-sensitive documents
2. **User perspective** - Customized explanation based on role
3. **Suggested questions** - Guide users to ask relevant questions
4. **Clear language** - Avoid legal jargon in responses
5. **Visual feedback** - Loading states, emojis, color coding

**Accessibility:**
- Portuguese language throughout
- Simple, clear language
- Visual icons for status (✅❌⚠️)
- Mobile-friendly interface
- Legal disclaimer visible

---

## 🐛 Common Issues & Solutions

### Issue: Tesseract not found
```bash
# Solution: Install Tesseract
sudo apt-get install tesseract-ocr tesseract-ocr-por
# Or run: ./install_tesseract.sh
```

### Issue: OpenCV import fails
```python
# Solution: Already handled gracefully
# CV2_AVAILABLE flag manages fallback (app.py:31-37)
# No action needed - basic processing will work
```

### Issue: Gemini API rate limit
```python
# Solution: Multi-model fallback handles this
# System automatically tries next model in priority list
# Check model_usage_stats for patterns
```

### Issue: Memory errors on Render
```python
# Solution: Already optimized in gunicorn_config.py
# - Reduced to 2 workers
# - Request recycling enabled
# - Preload app for memory sharing
# If persistent: reduce CACHE_EXPIRATION or disable caching
```

### Issue: Temporary files not cleaning up
```python
# Solution: Check cleanup thread is running
# Thread starts automatically on app load (app.py:165)
# Manual cleanup: limpar_arquivos_expirados()
# Verify TEMP_FILE_EXPIRATION setting
```

---

## 📊 Statistics & Monitoring

### Health Check Endpoint
```bash
GET /health
```
Returns:
- Application status
- Gemini API configuration status
- Tesseract availability
- Total documents processed
- Documents processed today

### Statistics Endpoint
```bash
GET /estatisticas
```
Returns (LGPD-compliant aggregates only):
- Total documents
- Today's count
- Count by document type
- Most common type
- Milestone progress

### Logging
All logs use Python logging module:
- INFO: Normal operations, statistics
- WARNING: Fallbacks, missing optional features
- ERROR: Failures, exceptions

**Key log patterns:**
- `✅` - Success
- `⚠️` - Warning/Fallback
- `❌` - Error
- `📊` - Statistics
- `🗑️` - LGPD cleanup
- `🔄` - Background tasks

---

## 🔄 Background Tasks

### Automatic Cleanup Thread (LGPD)
- **Frequency**: Every 60 seconds
- **Function**: `limpar_arquivos_expirados()` (app.py:126)
- **Purpose**: Delete temp files older than 30 minutes
- **Thread**: Daemon thread (exits with main process)

### Database Cleanup Thread (LGPD)
- **Frequency**: Every 24 hours
- **Function**: `limpar_estatisticas_antigas()` (database.py:175)
- **Purpose**: Delete daily stats older than 30 days
- **Thread**: Daemon thread in database module

### Rate Limit Cleanup
- **Frequency**: Every request check
- **Function**: `cleanup_old_requests()` (app.py:192)
- **Purpose**: Remove IP counters older than 1 minute

---

## 🎨 Frontend Customization

### Color Scheme (CSS Variables)
```css
:root {
    --primary: #2c4f5e;       /* Dark teal */
    --primary-dark: #1a3540;  /* Darker teal */
    --secondary: #b8963c;     /* Gold */
    --danger: #dc3545;        /* Red */
    --warning: #fbbc04;       /* Yellow */
    --success: #28a745;       /* Green */
    --dark: #202124;          /* Almost black */
    --light: #f8f9fa;         /* Off-white */
    --border: #dadce0;        /* Light gray */
}
```

### Document Type Badges
- Mandado (summons): Red, blinking animation
- Sentença (sentence): Primary color
- Acórdão (ruling): Primary color
- Custom types: Primary color

### Urgency Levels
- **Máxima** (Maximum): Red, pulsing animation
- **Alta** (High): Yellow/orange
- **Média** (Medium): Light gray

---

## 🔮 Future Considerations

### When adding features:
1. **Maintain LGPD compliance** - No personal data storage
2. **Test memory usage** - Render free tier has 512MB limit
3. **Consider mobile users** - Test on small screens
4. **Update documentation** - Keep this CLAUDE.md current
5. **Log appropriately** - Use emoji prefixes for clarity
6. **Handle errors gracefully** - Always provide fallbacks
7. **Think about cleanup** - What needs automatic deletion?

### Potential enhancements:
- Email notifications for urgent documents
- Multiple language support (Spanish, English)
- User accounts (requires LGPD compliance review)
- Document comparison feature
- Batch processing
- API for third-party integration
- Webhook notifications

---

## 📚 Additional Resources

### Official Documentation
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Google Gemini API](https://ai.google.dev/docs)
- [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [Render Deployment](https://render.com/docs)

### Brazilian Legal Context
- **LGPD**: Lei Geral de Proteção de Dados (Brazilian GDPR)
- **Target users**: Brazilian citizens navigating legal system
- **Document types**: Court decisions, summons, rulings, legal notices
- **Language**: Brazilian Portuguese

### Project Contact
- **Organization**: INOVASSOL
- **Purpose**: Legal document accessibility for citizens
- **Deployment**: https://entenda-aqui.onrender.com (or similar)

---

## ⚠️ Critical Warnings

### DO NOT:
1. ❌ Store document content in database
2. ❌ Log sensitive personal information
3. ❌ Commit API keys to repository
4. ❌ Increase Gunicorn workers beyond 2 (memory limit)
5. ❌ Disable automatic cleanup threads
6. ❌ Remove LGPD compliance measures
7. ❌ Use blocking operations in request handlers
8. ❌ Store files permanently (all must be temporary)

### ALWAYS:
1. ✅ Test LGPD compliance for new features
2. ✅ Maintain Portuguese language for user-facing content
3. ✅ Provide fallback options for all critical features
4. ✅ Log with appropriate emoji prefixes
5. ✅ Use thread-safe operations for shared resources
6. ✅ Update this CLAUDE.md when architecture changes
7. ✅ Test on Render free tier constraints
8. ✅ Validate file uploads thoroughly

---

## 🤝 Contributing Guidelines

When working on this project as an AI assistant:

1. **Understand context**: Read relevant sections of this guide
2. **Maintain conventions**: Follow established patterns
3. **Test thoroughly**: Manual testing before pushing
4. **Document changes**: Update comments and this guide
5. **Consider users**: Brazilian citizens with limited legal knowledge
6. **Respect constraints**: Memory, processing time, API limits
7. **Prioritize LGPD**: Privacy is not optional
8. **Think accessibility**: Clear language, visual feedback

---

## 📞 Quick Reference

### Most frequently edited files:
- `app.py` - Backend logic, endpoints, AI integration
- `templates/index.html` - Frontend UI, JavaScript
- `database.py` - Statistics (rarely modified)
- `requirements.txt` - Dependencies (when adding packages)

### Most common tasks:
- Add Gemini model: Update GEMINI_MODELS (app.py:54-92)
- Modify UI: Edit templates/index.html
- Add endpoint: Create route in app.py
- Update dependencies: Edit requirements.txt
- Change deployment: Modify render.yaml or gunicorn_config.py
- Add statistics: Modify database.py (ensure LGPD compliance)

### Critical endpoints:
- `/` - Main interface
- `/processar` - Document processing (POST)
- `/chat` - Chat questions (POST)
- `/health` - Health check (GET)
- `/estatisticas` - Statistics (GET)
- `/download_pdf` - Download simplified PDF (GET)

---

**Last Updated**: 2025-11-17
**Version**: 1.0
**Maintained by**: Claude AI assistants working on this project
