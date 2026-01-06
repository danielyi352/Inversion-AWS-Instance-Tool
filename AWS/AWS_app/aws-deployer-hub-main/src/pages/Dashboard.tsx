import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { InversionDeployer } from '@/components/deployer/InversionDeployer';
//blah

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

const Dashboard = () => {
  const navigate = useNavigate();

  useEffect(() => {
    // Check if user is authenticated
    const userSessionId = localStorage.getItem('user_session_id');
    
    if (!userSessionId) {
      navigate('/login');
      return;
    }

    // Verify session is still valid
    fetch(`${API_BASE}/auth/me`, {
      headers: {
        'X-User-Session-ID': userSessionId,
      },
    })
      .then((res) => {
        if (!res.ok) {
          localStorage.removeItem('user_session_id');
          navigate('/login');
        }
      })
      .catch(() => {
        localStorage.removeItem('user_session_id');
        navigate('/login');
      });
  }, [navigate]);

  return <InversionDeployer />;
};

export default Dashboard;
