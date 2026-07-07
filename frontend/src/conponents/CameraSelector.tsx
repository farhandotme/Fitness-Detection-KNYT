import { useEffect, useState } from "react";

interface CameraSelectorProps {
  onCameraChange: (deviceId: string) => void;
}

function CameraSelector({ onCameraChange }: CameraSelectorProps) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);

  useEffect(() => {
    loadDevices();
  }, []);

  async function loadDevices() {
    try {
      await navigator.mediaDevices.getUserMedia({
        video: true,
      });

      const allDevices = await navigator.mediaDevices.enumerateDevices();

      const cameras = allDevices.filter(
        (device) => device.kind === "videoinput",
      );

      setDevices(cameras);

      if (cameras.length > 0) {
        onCameraChange(cameras[0].deviceId);
      }
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <select
      className="camera-select"
      onChange={(e) => onCameraChange(e.target.value)}
    >
      {devices.map((camera) => (
        <option key={camera.deviceId} value={camera.deviceId}>
          {camera.label || "Unknown camera"}
        </option>
      ))}
    </select>
  );
}

export default CameraSelector;
