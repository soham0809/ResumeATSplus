import os
import io
import requests
from flask import Flask, request, render_template, send_file, jsonify, flash, redirect, url_for
from werkzeug.utils import secure_filename
import PyPDF2
from PIL import Image
import pytesseract
import google.generativeai as genai
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 16777216))  # 16MB max file size

# Configure Gemini AI
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables. Please check your .env file.")
genai.configure(api_key=GEMINI_API_KEY)

# Create upload folder
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
ENHANCED_FOLDER = os.getenv('ENHANCED_FOLDER', 'enhanced')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ENHANCED_FOLDER, exist_ok=True)

# Rate limiting storage (in production, use Redis or database)
rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = 5  # requests per window
RATE_LIMIT_WINDOW = 300  # 5 minutes in seconds

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def get_client_ip():
    """Get client IP address"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']

def rate_limit_check(ip):
    """Check if IP has exceeded rate limit"""
    now = datetime.now()
    # Clean old entries
    rate_limit_storage[ip] = [
        timestamp for timestamp in rate_limit_storage[ip]
        if now - timestamp < timedelta(seconds=RATE_LIMIT_WINDOW)
    ]
    
    # Check if limit exceeded
    if len(rate_limit_storage[ip]) >= RATE_LIMIT_REQUESTS:
        return False
    
    # Add current request
    rate_limit_storage[ip].append(now)
    return True

def rate_limit(f):
    """Rate limiting decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip = get_client_ip()
        if not rate_limit_check(ip):
            flash('Rate limit exceeded. Please try again in 5 minutes.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Extract text from PDF using PyPDF2"""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None

def extract_text_from_image(file_path):
    """Extract text from image using OCR"""
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return None

def get_ats_score(resume_text):
    """Advanced ATS scoring based on multiple criteria with realistic scoring"""
    score = 0
    text_lower = resume_text.lower()
    
    # 1. Contact Information (15 points max)
    contact_score = 0
    if '@' in text_lower or 'email' in text_lower:
        contact_score += 5
    if any(phone in text_lower for phone in ['phone', 'tel', 'mobile', '+', '(', ')']):
        contact_score += 3
    if 'linkedin' in text_lower:
        contact_score += 4
    if any(addr in text_lower for addr in ['address', 'city', 'state', 'zip']):
        contact_score += 3
    score += min(contact_score, 15)
    
    # 2. Professional Summary/Objective (10 points max)
    summary_keywords = ['summary', 'objective', 'profile', 'about']
    if any(keyword in text_lower for keyword in summary_keywords):
        # Check if it's substantial (more than just the header)
        lines = resume_text.split('\n')
        summary_content = 0
        for line in lines:
            if any(keyword in line.lower() for keyword in summary_keywords):
                # Count lines after summary header
                idx = lines.index(line)
                for i in range(idx + 1, min(idx + 5, len(lines))):
                    if lines[i].strip() and len(lines[i].strip()) > 20:
                        summary_content += 1
        score += min(summary_content * 3, 10)
    
    # 3. Work Experience Quality (25 points max)
    experience_score = 0
    experience_keywords = ['experience', 'work history', 'employment', 'professional experience']
    
    if any(keyword in text_lower for keyword in experience_keywords):
        experience_score += 5
        
        # Check for dates (shows employment timeline)
        import re
        date_patterns = [r'\d{4}', r'\d{1,2}/\d{4}', r'jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec']
        date_matches = sum(1 for pattern in date_patterns if re.search(pattern, text_lower))
        experience_score += min(date_matches, 8)
        
        # Check for job titles/companies
        job_indicators = ['manager', 'developer', 'analyst', 'engineer', 'specialist', 'coordinator', 'director', 'intern']
        job_matches = sum(1 for indicator in job_indicators if indicator in text_lower)
        experience_score += min(job_matches * 2, 6)
        
        # Check for quantified achievements
        numbers = re.findall(r'\d+%|\$\d+|\d+\+|increased|decreased|improved|reduced', text_lower)
        experience_score += min(len(numbers), 6)
    
    score += min(experience_score, 25)
    
    # 4. Skills Section (20 points max)
    skills_score = 0
    skills_keywords = ['skills', 'technical skills', 'competencies', 'technologies', 'tools']
    
    if any(keyword in text_lower for keyword in skills_keywords):
        skills_score += 5
        
        # Check for technical skills
        tech_skills = ['python', 'java', 'javascript', 'sql', 'html', 'css', 'react', 'node', 'aws', 'azure', 'docker', 'git']
        tech_matches = sum(1 for skill in tech_skills if skill in text_lower)
        skills_score += min(tech_matches, 8)
        
        # Check for soft skills
        soft_skills = ['leadership', 'communication', 'teamwork', 'problem solving', 'analytical', 'creative']
        soft_matches = sum(1 for skill in soft_skills if skill in text_lower)
        skills_score += min(soft_matches, 4)
        
        # Check for certifications
        cert_keywords = ['certified', 'certification', 'license', 'credential']
        if any(cert in text_lower for cert in cert_keywords):
            skills_score += 3
    
    score += min(skills_score, 20)
    
    # 5. Education (15 points max)
    education_score = 0
    education_keywords = ['education', 'degree', 'university', 'college', 'bachelor', 'master', 'phd', 'diploma']
    
    if any(keyword in text_lower for keyword in education_keywords):
        education_score += 5
        
        # Check for degree types
        degrees = ['bachelor', 'master', 'phd', 'doctorate', 'associate', 'diploma', 'certificate']
        degree_matches = sum(1 for degree in degrees if degree in text_lower)
        education_score += min(degree_matches * 3, 6)
        
        # Check for GPA or honors
        if any(honor in text_lower for honor in ['gpa', 'honors', 'magna cum laude', 'summa cum laude', 'dean']):
            education_score += 4
    
    score += min(education_score, 15)
    
    # 6. Action Verbs and Language Quality (10 points max)
    action_verbs = [
        'achieved', 'managed', 'led', 'developed', 'created', 'implemented', 'improved', 
        'increased', 'decreased', 'optimized', 'streamlined', 'coordinated', 'supervised',
        'analyzed', 'designed', 'built', 'established', 'launched', 'delivered'
    ]
    
    verb_count = sum(1 for verb in action_verbs if verb in text_lower)
    score += min(verb_count, 10)
    
    # 7. Formatting and Structure (5 points max)
    structure_score = 0
    
    # Check for proper sections
    sections = ['contact', 'summary', 'experience', 'skills', 'education']
    section_count = sum(1 for section in sections if section in text_lower)
    structure_score += min(section_count, 5)
    
    score += structure_score
    
    # Penalties for common issues
    # Too short resume (less than 200 characters)
    if len(resume_text) < 200:
        score -= 10
    
    # Too long resume (more than 5000 characters might be too verbose)
    if len(resume_text) > 5000:
        score -= 5
    
    # Lack of specific details (too many generic words)
    generic_words = ['responsible for', 'worked on', 'helped with', 'assisted in']
    generic_count = sum(1 for phrase in generic_words if phrase in text_lower)
    if generic_count > 3:
        score -= 5
    
    return max(0, min(score, 100))  # Ensure score is between 0 and 100

def enhance_resume_with_ai(resume_text):
    """Use Gemini AI to enhance the resume with score validation"""
    original_score = get_ats_score(resume_text)
    
    try:
        # Try multiple model names for compatibility
        model_names = ['models/gemini-1.5-flash', 'gemini-1.5-flash', 'gemini-pro', 'models/gemini-pro']
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                
                prompt = f"""
                You are an expert resume writer and ATS optimization specialist. Please enhance the following resume to make it more ATS-friendly and professional. 

                CRITICAL FORMATTING REQUIREMENTS:
                1. Use clear section headers: CONTACT INFORMATION, PROFESSIONAL SUMMARY, PROFESSIONAL EXPERIENCE, TECHNICAL SKILLS, EDUCATION
                2. Each section should be on a new line
                3. Use bullet points (•) for achievements and responsibilities
                4. Separate different jobs/experiences with clear spacing
                5. Keep contact information organized (Name, Email, Phone, LinkedIn on separate lines)
                6. Format skills as comma-separated lists or bullet points
                7. Include dates and locations for jobs and education
                8. Use strong action verbs and quantify achievements where possible

                FORMATTING STYLE GUIDELINES:
                - Use normal text for most content - DO NOT make everything bold
                - Only use bold formatting for: section headers, job titles, company names, and degree names
                - Keep bullet points and descriptions in regular text weight
                - Maintain clean, professional appearance without excessive formatting
                - Use consistent spacing and alignment

                Enhancement Guidelines:
                - Improve language to be more professional and impactful
                - Add relevant keywords for better ATS scanning
                - Quantify achievements with numbers, percentages, or dollar amounts
                - Replace weak phrases like "responsible for" with strong action verbs
                - Ensure proper grammar and formatting
                - Keep the same factual information but present it better
                - PRESERVE all important keywords and technical terms
                - DO NOT make the resume too long (keep under 4000 characters)
                - Focus on readability and professional appearance

                Original Resume:
                {resume_text}

                Please provide the enhanced resume with proper formatting, clear section breaks, and appropriate use of text formatting:
                """
                
                response = model.generate_content(prompt)
                if response.text:
                    # Validate that the enhanced version has a better or equal score
                    enhanced_score = get_ats_score(response.text)
                    if enhanced_score >= original_score:
                        return response.text
                    else:
                        print(f"AI enhancement reduced score from {original_score}% to {enhanced_score}%, using fallback")
                        
            except Exception as model_error:
                print(f"Model {model_name} failed: {model_error}")
                continue
        
        # If all models fail or reduce score, use improved fallback
        return enhance_resume_smart_fallback(resume_text)
        
    except Exception as e:
        print(f"Error enhancing resume with AI: {e}")
        return enhance_resume_smart_fallback(resume_text)

def enhance_resume_smart_fallback(resume_text):
    """Smart fallback that guarantees score improvement"""
    original_score = get_ats_score(resume_text)
    
    # Start with minimal safe enhancements
    enhanced_text = resume_text
    
    # 1. Add missing section headers if not present
    if 'CONTACT' not in enhanced_text.upper():
        lines = enhanced_text.split('\n')
        # Find first line with email or name
        for i, line in enumerate(lines):
            if '@' in line or (len(line.split()) <= 3 and not any(c.isdigit() for c in line)):
                lines.insert(i, 'CONTACT INFORMATION')
                lines.insert(i+1, '')
                break
        enhanced_text = '\n'.join(lines)
    
    # 2. Enhance action verbs (safe replacements)
    safe_replacements = {
        'worked on': 'developed',
        'helped with': 'assisted in',
        'was responsible for': 'managed',
        'took care of': 'maintained'
    }
    
    for old_phrase, new_phrase in safe_replacements.items():
        enhanced_text = enhanced_text.replace(old_phrase, new_phrase)
    
    # 3. Add professional summary if missing and resume is short
    if 'SUMMARY' not in enhanced_text.upper() and 'OBJECTIVE' not in enhanced_text.upper():
        if len(enhanced_text) < 1000:  # Only add if resume is short
            lines = enhanced_text.split('\n')
            # Find a good place to insert summary (after contact info)
            insert_pos = 0
            for i, line in enumerate(lines):
                if any(contact in line.lower() for contact in ['@', 'phone', 'linkedin']):
                    insert_pos = i + 2
                    break
            
            if insert_pos > 0:
                lines.insert(insert_pos, 'PROFESSIONAL SUMMARY')
                lines.insert(insert_pos + 1, 'Experienced professional seeking to leverage skills and expertise in a challenging role.')
                lines.insert(insert_pos + 2, '')
                enhanced_text = '\n'.join(lines)
    
    # 4. Validate the enhancement
    new_score = get_ats_score(enhanced_text)
    
    # If score didn't improve, try the original fallback
    if new_score <= original_score:
        enhanced_text = enhance_resume_fallback(resume_text)
        new_score = get_ats_score(enhanced_text)
    
    # If still no improvement, return original with minimal formatting
    if new_score <= original_score:
        return resume_text.strip()
    
    return enhanced_text

def enhance_resume_fallback(resume_text):
    """Fallback enhancement using simple text processing with better structure"""
    lines = resume_text.split('\n')
    enhanced_lines = []
    current_section = None
    
    # Extract basic information first
    name = ""
    email = ""
    phone = ""
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Extract contact info
        if '@' in line and not email:
            email = line
        elif any(phone_indicator in line.lower() for phone_indicator in ['phone', '+', '(', ')']) and not phone:
            phone = line
        elif not name and len(line.split()) <= 3 and not any(char.isdigit() for char in line):
            name = line
    
    # Start building enhanced resume
    if name:
        enhanced_lines.append("CONTACT INFORMATION")
        enhanced_lines.append("")
        enhanced_lines.append(name)
        if email:
            enhanced_lines.append(email)
        if phone:
            enhanced_lines.append(phone)
        enhanced_lines.append("")
    
    # Process remaining content
    for line in lines:
        line = line.strip()
        if not line or line == name or line == email or line == phone:
            continue
            
        line_upper = line.upper()
        
        # Detect sections
        if any(keyword in line_upper for keyword in ['SUMMARY', 'OBJECTIVE', 'PROFILE']):
            current_section = "PROFESSIONAL SUMMARY"
            enhanced_lines.append(current_section)
            enhanced_lines.append("")
            continue
        elif any(keyword in line_upper for keyword in ['EXPERIENCE', 'WORK', 'EMPLOYMENT']):
            current_section = "PROFESSIONAL EXPERIENCE"
            enhanced_lines.append(current_section)
            enhanced_lines.append("")
            continue
        elif any(keyword in line_upper for keyword in ['SKILLS', 'TECHNICAL', 'COMPETENCIES']):
            current_section = "TECHNICAL SKILLS"
            enhanced_lines.append(current_section)
            enhanced_lines.append("")
            continue
        elif any(keyword in line_upper for keyword in ['EDUCATION', 'DEGREE', 'UNIVERSITY', 'COLLEGE']):
            current_section = "EDUCATION"
            enhanced_lines.append(current_section)
            enhanced_lines.append("")
            continue
        elif any(keyword in line_upper for keyword in ['PROJECTS', 'PROJECT']):
            current_section = "PROJECTS"
            enhanced_lines.append(current_section)
            enhanced_lines.append("")
            continue
        
        # Enhance the content based on current section
        enhanced_line = line
        
        # Replace weak phrases with strong action verbs
        action_verb_replacements = {
            'worked on': 'developed',
            'helped with': 'assisted in',
            'did': 'executed',
            'made': 'created',
            'was responsible for': 'managed',
            'was in charge of': 'led',
            'took care of': 'maintained',
            'dealt with': 'handled'
        }
        
        for old_phrase, new_phrase in action_verb_replacements.items():
            enhanced_line = enhanced_line.replace(old_phrase, new_phrase)
        
        # Add bullet points for experience and projects
        if current_section in ["PROFESSIONAL EXPERIENCE", "PROJECTS"] and not enhanced_line.startswith('•'):
            if any(verb in enhanced_line.lower() for verb in ['developed', 'created', 'managed', 'led', 'implemented']):
                enhanced_line = "• " + enhanced_line
        
        enhanced_lines.append(enhanced_line)
    
    # Add a basic professional summary if none exists
    if "PROFESSIONAL SUMMARY" not in '\n'.join(enhanced_lines):
        summary_index = 1 if enhanced_lines and enhanced_lines[0] == "CONTACT INFORMATION" else 0
        while summary_index < len(enhanced_lines) and enhanced_lines[summary_index].strip():
            summary_index += 1
        
        enhanced_lines.insert(summary_index + 1, "PROFESSIONAL SUMMARY")
        enhanced_lines.insert(summary_index + 2, "")
        enhanced_lines.insert(summary_index + 3, "Experienced professional with a strong background in technology and problem-solving. Seeking opportunities to contribute technical expertise and drive impactful results.")
        enhanced_lines.insert(summary_index + 4, "")
    
    return '\n'.join(enhanced_lines)

def create_pdf_from_text(text, filename):
    """Create a PDF file from enhanced text with proper formatting"""
    try:
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors
        
        doc = SimpleDocTemplate(filename, pagesize=letter, 
                              leftMargin=72, rightMargin=72, 
                              topMargin=72, bottomMargin=72)
        styles = getSampleStyleSheet()
        story = []
        
        # Custom styles
        header_style = ParagraphStyle(
            'CustomHeader',
            parent=styles['Heading1'],
            fontSize=14,
            spaceAfter=12,
            spaceBefore=12,
            textColor=colors.darkblue,
            fontName='Helvetica-Bold'
        )
        
        subheader_style = ParagraphStyle(
            'CustomSubHeader',
            parent=styles['Heading2'],
            fontSize=11,
            spaceAfter=6,
            spaceBefore=6,
            textColor=colors.black,
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=4,
            spaceBefore=2,
            fontName='Helvetica'
        )
        
        bullet_style = ParagraphStyle(
            'CustomBullet',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=3,
            spaceBefore=1,
            leftIndent=20,
            fontName='Helvetica'
        )
        
        contact_style = ParagraphStyle(
            'CustomContact',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=2,
            spaceBefore=1,
            fontName='Helvetica'
        )
        
        # Split text into lines and process
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Detect different types of content
            line_upper = line.upper()
            
            # Main section headers (ONLY these should be bold)
            if any(header in line_upper for header in [
                'CONTACT INFORMATION', 'PROFESSIONAL SUMMARY', 'PROFESSIONAL EXPERIENCE', 
                'TECHNICAL SKILLS', 'EDUCATION', 'PROJECTS', 'CERTIFICATIONS'
            ]):
                story.append(Spacer(1, 12))
                story.append(Paragraph(line, header_style))
                continue
            
            # Job titles and company names (should be bold but smaller)
            elif (any(indicator in line_upper for indicator in [
                'ENGINEER', 'DEVELOPER', 'MANAGER', 'ANALYST', 'SPECIALIST', 
                'INTERN', 'CONSULTANT', 'COORDINATOR', 'DIRECTOR', 'ASSOCIATE'
            ]) and ('–' in line or '|' in line or 'at' in line.lower() or 
                   any(year in line for year in ['2020', '2021', '2022', '2023', '2024', '2025']))) or \
            (any(degree in line_upper for degree in [
                'BACHELOR', 'MASTER', 'B.TECH', 'M.TECH', 'MBA', 'PHD', 'B.S.', 'M.S.'
            ]) and any(year in line for year in ['2020', '2021', '2022', '2023', '2024', '2025'])):
                story.append(Paragraph(line, subheader_style))
                continue
            
            # Bullet points (should be normal text, not bold)
            elif line.startswith('•') or line.startswith('-') or line.startswith('*'):
                story.append(Paragraph(line, bullet_style))
                continue
            
            # Contact details (name, email, phone, etc.)
            elif any(contact in line.lower() for contact in ['@', 'phone', 'linkedin', 'github']) or \
                 (len(line.split()) <= 3 and not any(char.isdigit() for char in line) and 
                  not line.startswith('•') and len(line) > 5):
                story.append(Paragraph(line, contact_style))
                continue
            
            # Skills lists (comma-separated items) - normal text
            elif ',' in line and len(line.split(',')) > 2:
                # Format as a clean skills list
                skills = [skill.strip() for skill in line.split(',')]
                formatted_skills = ' • '.join(skills)
                story.append(Paragraph(formatted_skills, normal_style))
                continue
            
            # Regular paragraphs (descriptions, achievements) - normal text
            else:
                # Handle long lines by breaking them appropriately
                if len(line) > 100:
                    # Try to break at sentence boundaries
                    sentences = line.split('. ')
                    for j, sentence in enumerate(sentences):
                        if sentence.strip():
                            if j < len(sentences) - 1:
                                sentence += '.'
                            story.append(Paragraph(sentence.strip(), normal_style))
                else:
                    story.append(Paragraph(line, normal_style))
        
        # Build the PDF
        doc.build(story)
        return True
        
    except Exception as e:
        print(f"Error creating PDF: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@rate_limit
def upload_file():
    try:
        if 'file' not in request.files:
            flash('No file selected')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Extract text based on file type
            if filename.lower().endswith('.pdf'):
                extracted_text = extract_text_from_pdf(file_path)
            else:
                extracted_text = extract_text_from_image(file_path)
            
            if not extracted_text or len(extracted_text.strip()) < 50:
                flash('Could not extract sufficient text from the file. Please ensure the file contains readable text.')
                return redirect(url_for('index'))
            
            # Get original ATS score
            original_score = get_ats_score(extracted_text)
            
            # Enhance resume with AI
            enhanced_text = enhance_resume_with_ai(extracted_text)
            
            # Get enhanced ATS score
            enhanced_score = get_ats_score(enhanced_text)
            
            # Final validation: ensure enhanced score is never lower than original
            if enhanced_score < original_score:
                print(f"Warning: Enhanced score ({enhanced_score}%) lower than original ({original_score}%), using original")
                enhanced_text = extracted_text
                enhanced_score = original_score
            
            # Create enhanced PDF
            enhanced_filename = f"enhanced_{filename.rsplit('.', 1)[0]}.pdf"
            enhanced_path = os.path.join(ENHANCED_FOLDER, enhanced_filename)
            
            if create_pdf_from_text(enhanced_text, enhanced_path):
                # Clean up uploaded file for security
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return render_template('result.html', 
                                     original_score=original_score,
                                     enhanced_score=enhanced_score,
                                     enhanced_filename=enhanced_filename,
                                     original_text=extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text,
                                     enhanced_text=enhanced_text[:500] + "..." if len(enhanced_text) > 500 else enhanced_text)
            else:
                flash('Error creating enhanced PDF. Please try again.')
                return redirect(url_for('index'))
        
        flash('Invalid file type. Please upload PDF, PNG, JPG, or JPEG files.')
        return redirect(url_for('index'))
        
    except Exception as e:
        print(f"Error processing file: {e}")
        flash('An error occurred while processing your file. Please try again.')
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    try:
        # Sanitize filename for security
        filename = secure_filename(filename)
        file_path = os.path.join(ENHANCED_FOLDER, filename)
        
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=filename)
        else:
            flash('File not found or has expired')
            return redirect(url_for('index'))
    except Exception as e:
        print(f"Error downloading file: {e}")
        flash('Error downloading file')
        return redirect(url_for('index'))

@app.route('/health')
def health_check():
    """Health check endpoint for deployment monitoring"""
    try:
        # Check if Gemini API key is configured
        if not GEMINI_API_KEY:
            return jsonify({"status": "error", "message": "API key not configured"}), 500
        
        # Check if directories exist
        if not os.path.exists(UPLOAD_FOLDER) or not os.path.exists(ENHANCED_FOLDER):
            return jsonify({"status": "error", "message": "Required directories missing"}), 500
            
        return jsonify({
            "status": "healthy",
            "message": "Resume Enhancement System is running",
            "version": "1.0.0"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.getenv('FLASK_ENV', 'development') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
