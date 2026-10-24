import { useRef, useState } from 'react'
import Button from './Button.jsx'
import Icon from './Icon.jsx'

/* Drag-and-drop + "Choose PDF File" area. It only hands the chosen File to the
   parent (onFileSelected); validation and state live in the page. */
export default function UploadBox({ onFileSelected, disabled = false, maxSizeLabel = '10 MB' }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleFiles(fileList) {
    const file = fileList?.[0]
    if (file) onFileSelected(file)
  }

  function handleDrop(event) {
    event.preventDefault()
    setDragging(false)
    if (!disabled) handleFiles(event.dataTransfer.files)
  }

  return (
    <div
      className={`upload-box${dragging ? ' upload-box--active' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <span className="upload-box__icon" aria-hidden="true">
        <Icon name="upload" size={26} />
      </span>
      <p className="upload-box__title">Drag and drop your resume here</p>
      <p className="upload-box__or">or</p>

      <input
        ref={inputRef}
        id="resume-input"
        className="visually-hidden"
        type="file"
        accept="application/pdf,.pdf"
        tabIndex={-1}
        aria-label="Choose PDF resume"
        onChange={(event) => {
          handleFiles(event.target.files)
          event.target.value = '' // lets the same file be chosen again after removing it
        }}
        disabled={disabled}
      />
      <Button onClick={() => inputRef.current?.click()} disabled={disabled}>
        Choose PDF File
      </Button>

      <p className="upload-box__hint">
        PDF only <span aria-hidden="true">•</span> Maximum {maxSizeLabel}
      </p>
    </div>
  )
}
