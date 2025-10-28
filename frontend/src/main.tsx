import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import App from './App'
import './index.css'
import Home from './pages/Home'
import Recording from './pages/Recording'
import MeetingsList from './pages/MeetingsList'
import MeetingDetail from './pages/MeetingDetail'
import Calendar from './pages/Calendar'
import Settings from './pages/Settings'
import Help from './pages/Help'

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
    path: '/',
    element: <App />,
    errorElement: <ErrorPage />,
    children: [
      { index: true, element: <Home /> },
      { path: 'recording', element: <Recording /> },
      { path: 'meetings', element: <MeetingsList /> },
      { path: 'meetings/:id', element: <MeetingDetail /> },
      { path: 'calendar', element: <Calendar /> },
      { path: 'settings', element: <Settings /> },
      { path: 'help', element: <Help /> }
    ]
  }
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
)
