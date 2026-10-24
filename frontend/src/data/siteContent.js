/* Static page copy for the public pages (Home, About).
   This is marketing text, not application data, so it is kept separate from
   mockData.js and will NOT be replaced by backend calls. */

export const howItWorksSteps = [
  { id: 1, icon: 'file', title: 'Upload Resume', text: 'Upload your PDF resume' },
  { id: 2, icon: 'scan', title: 'AI Analysis', text: 'We analyze your skills' },
  { id: 3, icon: 'users', title: 'Get Job Matches', text: 'Find relevant opportunities' },
]

export const aboutFeatures = [
  {
    id: 'analysis',
    icon: 'scan',
    tone: 'blue',
    title: 'Smart Analysis',
    text: 'Extracts skills and experience from your resume using NLP.',
  },
  {
    id: 'jobs',
    icon: 'briefcase',
    tone: 'green',
    title: 'Relevant Jobs',
    text: 'Matches your profile with suitable job opportunities.',
  },
  {
    id: 'guidance',
    icon: 'target',
    tone: 'orange',
    title: 'Career Guidance',
    text: 'Provides skill gap analysis and learning recommendations.',
  },
]

/* Illustrative card shown beside the Home hero. */
export const heroPreview = {
  fileName: 'Your Resume.pdf',
  status: 'Analyzing ...',
  skills: ['Java', 'Spring Boot', 'React', 'MySQL'],
  matchLabel: '85% Match',
}
