export function AppFooter() {
  return (
    <footer className="app-footer">
      <span>Private workspace. Keep this screen out of public view.</span>
      <span className="app-footer-sep">·</span>
      <span>v1.0 &copy; {new Date().getFullYear()} Source Motion Physical Therapy LLC. All rights reserved.</span>
    </footer>
  );
}
