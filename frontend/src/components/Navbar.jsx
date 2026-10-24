import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/authContext.js'
import { getInitials } from '../utils/format.js'

const APP_ROUTES = ['/upload', '/dashboard', '/jobs', '/all-jobs']

const PUBLIC_LINKS = [
  { to: '/', label: 'Home', end: true },
  { to: '/about', label: 'About' },
]

const APP_LINKS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/all-jobs', label: 'All Jobs' },
  { to: '/about', label: 'About' },
]

export default function Navbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef(null)
  const { user, setUser } = useAuth()

  const onAppRoute = APP_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`))
  const appMode = onAppRoute || (pathname === '/about' && Boolean(user))

  useEffect(() => {
    if (!userMenuOpen) return undefined
    function onPointerDown(event) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) setUserMenuOpen(false)
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') setUserMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [userMenuOpen])

  const closeMenus = () => {
    setMenuOpen(false)
    setUserMenuOpen(false)
  }

  function handleLogout() {
    setUser(null)
    closeMenus()
    navigate('/login')
  }

  const links = appMode ? APP_LINKS : PUBLIC_LINKS

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <NavLink to="/" className="flex items-center gap-2" onClick={closeMenus}>
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600">
            <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </span>
          <span className="text-lg font-bold">
            <span className="text-gray-900">Resume</span>
            <span className="text-blue-600">AI</span>
          </span>
        </NavLink>

        <button
          type="button"
          className="md:hidden text-gray-600"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? '✕' : '☰'}
        </button>

        <nav className={`${menuOpen ? 'flex' : 'hidden'} md:flex items-center gap-6`}>
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `text-sm font-medium ${isActive ? 'text-blue-600' : 'text-gray-600 hover:text-blue-600'}`
              }
              onClick={closeMenus}
            >
              {link.label}
            </NavLink>
          ))}

          {appMode ? (
            <div className="relative" ref={userMenuRef}>
              <button
                type="button"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700"
                onClick={() => setUserMenuOpen((open) => !open)}
              >
                {getInitials(user?.name) || 'U'}
              </button>
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-40 rounded-lg border border-gray-200 bg-white py-2 shadow-lg">
                  <p className="px-3 py-1 text-sm text-gray-500">{user?.name ?? 'Account'}</p>
                  <button
                    type="button"
                    className="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    onClick={handleLogout}
                  >
                    Log out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <NavLink to="/login" className="text-sm font-medium text-gray-600 hover:text-blue-600" onClick={closeMenus}>
                Login
              </NavLink>
              <NavLink
                to="/signup"
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                onClick={closeMenus}
              >
                Sign Up
              </NavLink>
            </div>
          )}
        </nav>
      </div>
    </header>
  )
}