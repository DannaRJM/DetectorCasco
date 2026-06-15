module.exports = {
  apps: [
    {
      name: 'bluax-casco',
      script: 'python',
      args: '-u detector_casco.py',
      cwd: 'C:/Users/danna/OneDrive/Escritorio/DetectorCasco',
      interpreter: 'none',
      autorestart: true,
      restart_delay: 15000,
      max_restarts: 5,
      env: { PYTHONUTF8: '1' },
      log_file:   'C:/DetectorCasco/logs/casco.log',
      error_file: 'C:/DetectorCasco/logs/casco_err.log',
      time: true,
    },
  ],
};
