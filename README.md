# AI Resume Analyzer & Job Recommendation System

An intelligent resume analysis and job recommendation platform that helps users discover relevant job opportunities based on their resume, identify skill gaps, and plan their career growth.

## Overview

The AI Resume Analyzer & Job Recommendation System analyzes PDF resumes, extracts relevant skills, and recommends suitable job opportunities using Natural Language Processing (NLP) and Machine Learning techniques.

The project aims to help job seekers understand how their current skills align with job requirements and identify areas for improvement.

## Features

- **PDF Resume Upload:** Upload a resume in PDF format for analysis.
- **Resume Text Extraction:** Extract relevant text from uploaded resumes.
- **Skill Extraction:** Identify skills and relevant information from resume content.
- **Job Recommendations:** Recommend relevant job opportunities based on resume skills and job requirements.
- **Job Matching:** Use TF-IDF, cosine similarity, and skill matching to evaluate relevance.
- **Skill Gap Analysis:** Identify job-related skills that were not found in the resume.
- **Career Guidance:** Provide suggestions for suitable career paths and skills to develop.
- **Learning Roadmap:** Help users plan learning activities and practical projects.
- **Job Market Insights:** Explore trending skills and job roles using reliable market data, where available.

*Note: Features should be marked as completed only when they are implemented and tested in the current codebase. Career guidance, learning roadmaps, and job market insights may require additional implementation depending on the current project status.*

## Technology Stack

### Frontend
- React
- React Router
- CSS

### Backend
- Python
- FastAPI

### Database
- MySQL

### Machine Learning and NLP
- Scikit-learn
- TF-IDF
- Cosine Similarity
- Skill Matching
- Resume Text Processing

## How It Works

1. The user uploads a PDF resume.
2. The backend extracts text from the resume.
3. Relevant skills and information are identified.
4. The recommendation system compares the resume profile with available job data.
5. Relevant jobs are ranked and presented to the user.
6. Skill gaps and career development suggestions can help the user plan their next steps.

## Project Structure

The project contains separate frontend and backend applications.

```text
AI-Resume-Analyzer/
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
├── backend/
│   ├── main.py
│   ├── db.py
│   └── requirements.txt
├── .gitignore
└── README.md
```

*The structure above is illustrative. Update it to match the actual repository structure before publishing.*

## Getting Started

### Prerequisites

Install the following tools:

- Node.js and npm
- Python
- MySQL Server
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/Aman007-bit/AI-Resume-Analyzer.git
cd AI-Resume-Analyzer
```

### 2. Set Up the Backend

Open a terminal in the backend directory:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment on Windows Command Prompt:

```cmd
.venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Configure the required database connection settings using environment variables or the configuration method already implemented in the project.

**Never commit real database passwords, API keys, or secret configuration files.**

### 3. Set Up MySQL

Create the database using the project's existing database setup instructions.

Configure the required connection details securely. Use the actual schema and initialization process from the repository; do not assume that creating an empty database is sufficient.

### 4. Start the Backend

Run the following command if `main.py` exposes the FastAPI application as `app`:

```bash
python -m uvicorn main:app --reload
```

The development server typically runs at:

```text
http://127.0.0.1:8000
```

If enabled by the application, FastAPI's interactive API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

### 5. Set Up the Frontend

Open a separate terminal and navigate to the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite in the terminal.

*Use the actual scripts and folder names defined in the repository if they differ from these examples.*

## Security and Privacy

- Do not commit `.env` files, database credentials, or API keys.
- Do not upload private resumes, personal information, database dumps, or backups to the public repository.
- Keep virtual environments, `node_modules`, build outputs, and local runtime files out of version control.
- Validate uploaded PDF files on the backend.
- Use secure database configuration and appropriate access controls.
- Review all staged files before pushing changes to GitHub.

## Limitations

- Recommendation quality depends on the quality and completeness of available job data.
- Skills missing from a resume are not necessarily skills the user does not possess.
- Job matching scores indicate relevance, not the probability of receiving a job offer.
- Market trend insights require reliable, sufficiently recent data.
- No recommendation system can guarantee employment or 100% eligibility for all jobs.

## Future Improvements

Potential improvements include:

- More detailed career gap analysis
- Personalized learning roadmaps
- Current job market and trending skill analysis
- Verified recruitment contact discovery
- Assisted job application workflows
- Application tracking
- Improved recommendation evaluation and testing

These items should be considered planned work unless they are already implemented and verified.

## Contributing

Contributions, suggestions, and bug reports are welcome. Please describe proposed changes and test them before submitting a pull request.

## License

No license has been specified yet. Unless a license is added, do not assume that the repository is available for unrestricted reuse.

---

**Built with React, FastAPI, MySQL, Python, and Machine Learning.**