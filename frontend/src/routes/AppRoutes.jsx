import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from '../components/Layout.jsx'
import About from '../pages/About.jsx'
import Dashboard from '../pages/Dashboard.jsx'
import HomePage from '../pages/Home.jsx'
import JobDetails from '../pages/JobDetails.jsx'
import Login from '../pages/Login.jsx'
import RecommendedJobs from '../pages/RecommendedJobs.jsx'
import ResumeUpload from '../pages/ResumeUpload.jsx'
import SignUp from '../pages/SignUp.jsx'
import ProtectedRoute from './ProtectedRoute.jsx'
import AllJobs from '../pages/AllJobs.jsx'
import ForgotPassword from '../pages/ForgotPassword.jsx'

export default function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<SignUp />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/about" element={<About />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/upload" element={<ResumeUpload />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/jobs" element={<RecommendedJobs />} />
          <Route path="/jobs/:id" element={<JobDetails />} />
          <Route path="/all-jobs" element={<AllJobs />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}