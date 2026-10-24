import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { analyzeResume, validateResumeFile } from '../services/resumeService.js'

export default function ResumeUpload() {
  const navigate = useNavigate()
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef(null)

  const handleFile = useCallback((f) => {
    const validationError = validateResumeFile(f)
    if (validationError) {
      setError(validationError)
      setFile(null)
      return
    }
    setFile(f)
    setError('')
  }, [])

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0])
  }

  const handleAnalyze = async () => {
    if (!file) {
      setError('Please select a PDF resume first.')
      return
    }
    setError('')
    setStatus('analyzing')
    try {
      const result = await analyzeResume(file)
      const resumeId = result.resume_id ?? result.resumeId
      if (resumeId == null) throw new Error('Backend did not return a resume ID.')
      setStatus('done')
      navigate('/dashboard', { replace: true, state: { resumeId, resumeResult: result, recommendations: result.recommendations ?? [], recommendationError: result.recommendationError ?? null } })
    } catch (err) {
      setStatus('idle')
      setError(err?.message || 'Resume upload failed.')
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900">Upload Your Resume</h1>
      <p className="mt-2 text-gray-500">Upload your resume in PDF format to get started with AI analysis.</p>

      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`mt-8 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-16 transition-colors ${
          isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-white hover:border-blue-300 hover:bg-blue-50/30'
        }`}
      >
        <input ref={inputRef} type="file" accept=".pdf" className="hidden" onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
        <svg className={`h-12 w-12 ${isDragging ? 'text-blue-500' : 'text-gray-400'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>
        <p className="mt-4 text-base font-semibold text-gray-700">{isDragging ? 'Drop your file here' : 'Drag & drop your resume'}</p>
        <p className="mt-1 text-sm text-gray-500">or <span className="font-medium text-blue-600">browse files</span></p>
        <p className="mt-4 text-xs text-gray-400">PDF · Max 10MB</p>
      </div>

      {file && (
        <div className="mt-4 flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
              <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-800">{file.name}</p>
              <p className="text-xs text-gray-400">{(file.size / 1024).toFixed(1)} KB</p>
            </div>
          </div>
          <button onClick={() => setFile(null)} className="text-gray-400 hover:text-red-500">✕</button>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <button
        onClick={handleAnalyze}
        disabled={!file || status === 'analyzing'}
        className="mt-6 w-full rounded-lg bg-blue-600 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {status === 'analyzing' ? 'Analyzing your resume...' : 'Analyze Resume'}
      </button>

      <p className="mt-4 text-xs text-gray-400">Your resume is sent to the backend for analysis. Data is stored in the database.</p>
    </div>
  )
}