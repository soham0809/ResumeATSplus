# AI Resume Enhancement System

Transform your resume with AI-powered analysis and enhancement. Upload your resume, get an ATS score, and download a professionally enhanced version.

## 🚀 Quick Start

### 1. Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file with your API key
echo "GEMINI_API_KEY=your_api_key_here" > .env
echo "SECRET_KEY=your_secret_key_here" >> .env
```

### 2. Run Locally
```bash
python app.py
```
Visit `http://localhost:5000`

### 3. Workflow
1. **Upload** - Drop your resume (PDF/Image)
2. **Analyze** - Get ATS score and analysis
3. **Enhance** - AI improves content and formatting
4. **Download** - Get professional PDF

## 🔧 Features

- **ATS Scoring** - Comprehensive resume analysis
- **AI Enhancement** - Google Gemini AI optimization
- **Professional PDF** - Clean, formatted output
- **Rate Limiting** - API protection (5 requests/5min)
- **Secure** - Environment variables for credentials

## 📊 ATS Scoring (100 points)

| Category | Points | Criteria |
|----------|--------|----------|
| Contact Info | 15 | Email, phone, LinkedIn, address |
| Summary | 10 | Professional summary quality |
| Experience | 25 | Work history, achievements, dates |
| Skills | 20 | Technical/soft skills, certifications |
| Education | 15 | Degrees, institutions, honors |
| Language | 10 | Action verbs, quantified results |
| Structure | 5 | Formatting, organization |

## 🚀 Deploy to Vercel

### Step 1: Prepare Project
```bash
# Ensure all files are ready
git add .
git commit -m "Ready for deployment"
git push origin main
```

### Step 2: Deploy
1. Go to [vercel.com](https://vercel.com)
2. Click "New Project"
3. Import your GitHub repository
4. Vercel will auto-detect Flask

### Step 3: Environment Variables
In Vercel dashboard → Settings → Environment Variables:
```
GEMINI_API_KEY = your_actual_api_key
SECRET_KEY = your_secret_key
FLASK_ENV = production
```

### Step 4: Deploy
Click "Deploy" - your app will be live at `https://your-project.vercel.app`

## 📁 Project Structure
```
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── vercel.json        # Vercel configuration
├── .env              # Environment variables (local)
├── .gitignore        # Git ignore rules
├── templates/        # HTML templates
│   ├── base.html
│   ├── index.html
│   └── result.html
├── uploads/          # Temporary uploads
└── enhanced/         # Generated PDFs
```

## 🔒 Security

- API keys in environment variables
- Rate limiting (5 requests per 5 minutes per IP)
- Secure file upload validation
- Input sanitization

## 🛠️ Tech Stack

- **Backend**: Flask (Python)
- **AI**: Google Gemini API
- **PDF**: ReportLab, PyPDF2
- **OCR**: Tesseract
- **Frontend**: Bootstrap 5
- **Deploy**: Vercel, Render, Heroku ready
