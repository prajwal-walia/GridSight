import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  children: React.ReactNode;
  onClose: () => void;
  width?: number;
  height?: number;
}

export default function PiPWindow({
  children,
  onClose,
  width = 480,
  height = 720,
}: Props) {
  const [pipWindow, setPipWindow] = useState<Window | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    let pipWin: Window | null = null;
    closedRef.current = false;

    pipWin = window.open("", "_blank", `width=${width},height=${height},popup=yes`);
    if (!pipWin) {
      onClose(); // In case popup is blocked
      return;
    }

    pipWin.document.title = "GridSight — PiP";
    pipWin.document.body.style.margin = "0";
    pipWin.document.body.style.padding = "0";
    pipWin.document.body.style.backgroundColor = "#0A0A0F";
    pipWin.document.body.style.color = "#e5e7eb";
    pipWin.document.body.style.overflow = "hidden";

    // Copy stylesheets for Vite/Tailwind properly
    Array.from(document.styleSheets).forEach((sheet) => {
      if (sheet.href) {
        const newLink = document.createElement("link");
        newLink.rel = "stylesheet";
        newLink.href = sheet.href;
        pipWin!.document.head.appendChild(newLink);
      } else {
        try {
          if (sheet.cssRules) {
            const newStyle = document.createElement("style");
            Array.from(sheet.cssRules).forEach((rule) => {
              newStyle.appendChild(document.createTextNode(rule.cssText));
            });
            pipWin!.document.head.appendChild(newStyle);
          }
        } catch (e) {
          console.warn("Could not copy CSS rules:", e);
        }
      }
    });

    const mount = pipWin.document.createElement("div");
    mount.id = "pip-root";
    mount.style.width = "100%";
    mount.style.height = "100vh";
    mount.style.display = "flex";
    mount.style.flexDirection = "column";
    pipWin.document.body.appendChild(mount);
    containerRef.current = mount;

    pipWin.addEventListener("beforeunload", () => {
      if (!closedRef.current) {
        closedRef.current = true;
        onClose();
      }
    });

    setPipWindow(pipWin);

    return () => {
      closedRef.current = true;
      if (pipWin && !pipWin.closed) {
        pipWin.close();
      }
      setPipWindow(null);
      containerRef.current = null;
    };
  }, [width, height, onClose]);

  if (!pipWindow || !containerRef.current) return null;

  return createPortal(children, containerRef.current);
}
