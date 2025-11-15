import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import App from './App'
import './index.css'
import Home from './pages/Home'
import Recording from './pages/Recording'
import MeetingsList from './pages/MeetingsList'
import MeetingDetail from './pages/MeetingDetail'
import Calendar from './pages/Calendar'
import Settings from './pages/Settings'
import Help from './pages/Help'
import AuthLayout from './pages/AuthLayout'
import Login from './pages/Login'
import Register from './pages/Register'
import RequireAuth from './components/RequireAuth'
import { AuthProvider } from './contexts/AuthContext'
import { RecorderProvider } from './contexts/RecorderContext'

function ErrorPage() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-2">ページの読み込みに失敗しました</h1>
      <p className="opacity-80">URLをご確認のうえ、サイドバーから再度移動してください。</p>
    </div>
  )
}

const router = createBrowserRouter([
  {
    path: '/auth',
    element: <AuthLayout />,
    errorElement: <ErrorPage />,
    children: [
      { index: true, element: <Navigate to="login" replace /> },
      { path: 'login', element: <Login /> },
      { path: 'register', element: <Register /> },
    ],
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <App />
      </RequireAuth>
    ),
    errorElement: <ErrorPage />,
    children: [
      { index: true, element: <Home /> },
      { path: 'recording', element: <Recording /> },
      { path: 'meetings', element: <MeetingsList /> },
      { path: 'meetings/:id', element: <MeetingDetail /> },
      { path: 'calendar', element: <Calendar /> },
      { path: 'settings', element: <Settings /> },
      { path: 'help', element: <Help /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <RecorderProvider>
        <RouterProvider router={router} />
      </RecorderProvider>
    </AuthProvider>
  </React.StrictMode>
)
