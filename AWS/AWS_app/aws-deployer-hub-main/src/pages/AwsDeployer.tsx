import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { InversionDeployer } from '@/components/deployer/InversionDeployer';
import { getCurrentUser } from '@/lib/api';

const AwsDeployer = () => {
  const navigate = useNavigate();

  useEffect(() => {
    // Check if user is authenticated
    const userSessionId = localStorage.getItem('user_session_id');
    
    if (!userSessionId) {
      navigate('/login');
      return;
    }

    // Verify session is still valid
    getCurrentUser()
      .then(() => {
        // Session is valid, stay on page
      })
      .catch(() => {
        localStorage.removeItem('user_session_id');
        navigate('/login');
      });
  }, [navigate]);

  return <InversionDeployer />;
};

export default AwsDeployer;
