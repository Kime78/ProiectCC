import React, { useState, useEffect } from "react";
import axios from "axios";

// Environment variables populated by CI/CD
const API_URL = import.meta.env.VITE_API_URL || "";

function App() {
  const [products, setProducts] = useState([]);
  const [url, setUrl] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [loading, setLoading] = useState(false);

  // In a real application, you would implement an Amazon Cognito login flow here
  // and pass the resulting JWT token in the Authorization header.
  const headers = { 
    // "Authorization": `Bearer ${MY_COGNITO_JWT_TOKEN}` 
  };

  const fetchProducts = async () => {
    if (!API_URL) return;
    try {
      const res = await axios.get(`${API_URL}products`, { headers });
      setProducts(res.data.products || []);
    } catch (err) {
      console.error("Error fetching products:", err);
    }
  };

  const addProduct = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API_URL}product`, { url, target_price: targetPrice }, { headers });
      setUrl("");
      setTargetPrice("");
      fetchProducts();
    } catch (err) {
      console.error("Error adding product:", err);
    }
    setLoading(false);
  };

  const deleteProduct = async (id) => {
    try {
      await axios.delete(`${API_URL}product/${id}`, { headers });
      fetchProducts();
    } catch (err) {
      console.error("Error deleting product:", err);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, []);

  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>eMag Price Tracker</h1>
      
      {!API_URL && <p style={{ color: "red" }}>API URL is missing! Ensure .env is populated by CI/CD.</p>}

      <form onSubmit={addProduct} style={{ marginBottom: "2rem", display: "flex", gap: "10px" }}>
        <input 
          type="url" 
          placeholder="eMag Product URL" 
          value={url} 
          onChange={(e) => setUrl(e.target.value)} 
          required 
          style={{ width: "300px" }}
        />
        <input 
          type="number" 
          placeholder="Target Price (Lei)" 
          value={targetPrice} 
          onChange={(e) => setTargetPrice(e.target.value)} 
          required 
        />
        <button type="submit" disabled={loading}>
          {loading ? "Adding..." : "Add Product"}
        </button>
      </form>

      <h2>Tracked Products</h2>
      <ul>
        {products.map((p) => (
          <li key={p.id} style={{ marginBottom: "1rem" }}>
            <a href={p.url} target="_blank" rel="noreferrer">View Product</a> | 
            <b> Target:</b> {p.target_price} Lei | 
            <b> Last Checked:</b> {p.last_price} Lei
            <button onClick={() => deleteProduct(p.id)} style={{ marginLeft: "10px", color: "red" }}>Delete</button>
          </li>
        ))}
        {products.length === 0 && <p>No products tracked yet.</p>}
      </ul>
    </div>
  );
}

export default App;
