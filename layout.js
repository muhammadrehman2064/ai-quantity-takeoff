export const metadata = {
  title: "AI Quantity Takeoff",
  description: "AI-assisted construction drawing measurement and quantity takeoff"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "Arial, sans-serif", background: "#f5f7fa" }}>
        {children}
      </body>
    </html>
  );
}
