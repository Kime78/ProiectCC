import React, { useState, useEffect } from "react";
import axios from "axios";
import { Authenticator } from '@aws-amplify/ui-react';
import { fetchAuthSession } from 'aws-amplify/auth';

// Environment variables populated by CI/CD
const API_URL = import.meta.env.VITE_API_URL || "";

function App({ signOut, user }) {
  const [products, setProducts] = useState([]);
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingId, setCheckingId] = useState(null);
  const [logs, setLogs] = useState([]);

  const addLog = (msg, type = "info") => {
    setLogs((prev) => {
      const newLogs = [{ id: Date.now() + Math.random(), msg, type, time: new Date() }, ...prev];
      return newLogs.slice(0, 5); // keep max 5 logs
    });
  };

  const getErrorMessage = (err, fallback) => {
    if (err?.response?.data?.error) return err.response.data.error;
    if (err?.response?.data?.message) return err.response.data.message;
    if (err?.message) return err.message;
    return fallback;
  };

  const getHeaders = async () => {
    try {
      const session = await fetchAuthSession();
      // The API Gateway Cognito Authorizer expects the ID Token
      return { Authorization: session.tokens.idToken.toString() };
    } catch (e) {
      return {};
    }
  };

  const fetchProducts = async () => {
    if (!API_URL) return;
    try {
      const headers = await getHeaders();
      const res = await axios.get(`${API_URL}products`, { headers });
      setProducts(res.data.products || []);
    } catch (err) {
      console.error("Error fetching products:", err);
      addLog(`Failed to fetch products: ${getErrorMessage(err, "Unknown error")}`, "error");
    }
  };

  const addProduct = async (e) => {
    e.preventDefault();
    setLoading(true);
    addLog("Adding product...", "info");
    try {
      const headers = await getHeaders();
      await axios.post(`${API_URL}product`, { url }, { headers });
      setUrl("");
      fetchProducts();
      addLog("Product added successfully!", "success");
    } catch (err) {
      console.error("Error adding product:", err);
      addLog(`Failed to add product: ${getErrorMessage(err, "Unknown error")}`, "error");
    }
    setLoading(false);
  };

  const deleteProduct = async (id) => {
    try {
      const headers = await getHeaders();
      await axios.delete(`${API_URL}product/${id}`, { headers });
      fetchProducts();
      addLog("Product removed", "info");
    } catch (err) {
      console.error("Error deleting product:", err);
      addLog(`Failed to remove product: ${getErrorMessage(err, "Unknown error")}`, "error");
    }
  };

  const checkProduct = async (id) => {
    try {
      setCheckingId(id);
      addLog("Checking for price updates...", "info");
      const headers = await getHeaders();
      await axios.post(`${API_URL}product/${id}/check`, {}, { headers });
      fetchProducts(); // Refresh list to get updated time and price
      addLog("Price check complete!", "success");
    } catch (err) {
      console.error("Error checking product:", err);
      addLog(`Failed to check product: ${getErrorMessage(err, "Unknown error")}`, "error");
    } finally {
      setCheckingId(null);
    }
  };

  const getNextCheckTime = (lastCheckStamp) => {
    if (!lastCheckStamp) return "Waiting...";
    // Assuming EventBridge runs every 6 hours
    const nextTime = new Date((lastCheckStamp + 6 * 3600) * 1000);
    return nextTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  useEffect(() => {
    fetchProducts();
  }, []);

  // Option 1: Polling mechanism
  useEffect(() => {
    // Check if any product is currently being scraped (price is null or it's a specific placeholder)
    const isScraping = products.some(p => p.price === null || p.name === "Adding product..." || checkingId === p.id);

    let interval;
    if (isScraping) {
      // Poll every 5 seconds if a Fargate task is running
      interval = setInterval(() => {
        fetchProducts();
      }, 5000);
    }
    
    return () => clearInterval(interval);
  }, [products, checkingId]);

  return (
    <div className="min-h-screen bg-gray-100 p-4 sm:p-8">
      <div className="max-w-7xl mx-auto bg-white p-6 sm:p-10 rounded-xl shadow-lg">
        
        <div className="flex flex-col sm:flex-row justify-between items-center mb-8 border-b pb-4">
          <h1 className="text-3xl font-extrabold text-blue-900 mb-4 sm:mb-0">eMag Price Tracker</h1>
          <div className="flex items-center gap-4">
            <span className="text-gray-600 text-sm hidden sm:block">Logged in as <b>{user?.signInDetails?.loginId}</b></span>
            <button 
              onClick={signOut} 
              className="bg-red-50 text-red-600 hover:bg-red-100 font-semibold px-4 py-2 rounded-lg transition-colors border border-red-200"
            >
              Sign Out
            </button>
          </div>
        </div>
        
        {!API_URL && (
          <div className="bg-red-50 text-red-700 p-4 rounded-lg mb-6 border border-red-200">
            API URL is missing! Ensure .env is populated by CI/CD.
          </div>
        )}

        <form onSubmit={addProduct} className="flex flex-col sm:flex-row gap-4 mb-10 bg-gray-50 p-6 rounded-xl border border-gray-100">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">Add Product to Watchlist</label>
            <input 
              type="url" 
              placeholder="Paste eMag Product URL here..." 
              value={url} 
              onChange={(e) => setUrl(e.target.value)} 
              required 
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
            />
          </div>
          <div className="flex items-end">
            <button 
              type="submit" 
              disabled={loading} 
              className="w-full sm:w-auto bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-2.5 rounded-lg disabled:opacity-50 transition-colors shadow-sm"
            >
              {loading ? "Adding..." : "Watch Price"}
            </button>
          </div>
        </form>

        <h2 className="text-2xl font-bold text-gray-800 mb-6">Your Tracked Products</h2>
        
        {/* LOG MESSAGES UI */}
        {logs.length > 0 && (
          <div className="mb-6 space-y-2">
            {logs.map((log) => (
              <div key={log.id} className={`p-3 rounded-lg text-sm font-medium ${
                log.type === "error" ? "bg-red-50 text-red-700 border border-red-200" :
                log.type === "success" ? "bg-green-50 text-green-700 border border-green-200" :
                "bg-blue-50 text-blue-700 border border-blue-200"
              }`}>
                {log.time.toLocaleTimeString()} - {log.msg}
              </div>
            ))}
          </div>
        )}

        <div className="space-y-4">
          {products.map((p) => {
            const isChecking = checkingId === p.id;
            return (
            <div
              key={p.id}
              className={`border border-gray-200 rounded-xl p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center bg-white hover:border-blue-300 transition-colors shadow-sm ${
                isChecking ? "ring-2 ring-blue-200 bg-blue-50/40" : ""
              }`}
            >
              <div className="flex gap-4 flex-1 items-start w-full">
                {/* PRODUCT PHOTO */}
                <div className="w-20 h-20 flex-shrink-0 bg-gray-50 rounded-lg border border-gray-200 overflow-hidden flex items-center justify-center">
                  {p.image ? (
                    <img src={p.image} alt={p.name || 'product'} className="w-full h-full object-contain" />
                  ) : (
                    <span className="text-2xl">📦</span>
                  )}
                </div>
                
                <div className="truncate pr-4 flex-1 mb-4 sm:mb-0 w-full">
                  <a href={p.url} target="_blank" rel="noreferrer" className="text-gray-900 font-bold hover:underline hover:text-blue-600 truncate block text-lg mb-1">
                    {p.name || p.url}
                  </a>
                  {p.name && (
                    <a href={p.url} target="_blank" rel="noreferrer" className="text-gray-400 text-xs hover:text-blue-500 truncate block">
                      {p.url}
                    </a>
                  )}
                  <div className="text-sm text-gray-500 mt-2 flex flex-col sm:flex-row items-start sm:items-center gap-2">
                    <div className="flex items-center gap-2">
                      <span className="bg-gray-100 px-2 py-1 rounded">Last Checked Price:</span>
                      <span className="font-bold text-gray-800 text-lg">
                        {p.last_price != null ? `${p.last_price} Lei` : 'Waiting for first check...'}
                      </span>
                    </div>
                    <div className="text-xs text-blue-500 font-medium mt-1 sm:mt-0 sm:ml-4">
                      Next automatic check roughly around: {getNextCheckTime(p.last_check_time)}
                    </div>
                  </div>
                  <div className="text-xs text-gray-500 mt-2">
                    {p.last_check_time ? (
                      <>Last checked at {new Date(p.last_check_time * 1000).toLocaleString()}</>
                    ) : (
                      <>Not checked yet</>
                    )}
                  </div>
                  {isChecking && (
                    <div className="mt-2 inline-flex items-center gap-2 text-xs font-semibold text-blue-700 bg-blue-100 px-2 py-1 rounded-full">
                      <span className="h-2 w-2 rounded-full bg-blue-600 animate-pulse" />
                      Checking now...
                    </div>
                  )}
                </div>
              </div>
              <div className="flex flex-col sm:flex-row gap-2 w-full sm:w-auto mt-4 sm:mt-0">
                <button 
                  onClick={() => checkProduct(p.id)} 
                  disabled={isChecking}
                  className={`${isChecking ? 'bg-gray-100 text-gray-400' : 'text-blue-600 hover:bg-blue-50 hover:text-blue-800'} font-medium px-4 py-2 border border-blue-200 rounded-lg transition-colors whitespace-nowrap`}
                >
                  {isChecking ? 'Checking...' : 'Check Now'}
                </button>
                <button 
                  onClick={() => deleteProduct(p.id)} 
                  disabled={isChecking}
                  className="text-red-500 hover:text-red-700 font-medium px-4 py-2 border border-red-200 rounded-lg hover:bg-red-50 transition-colors whitespace-nowrap disabled:opacity-50"
                >
                  Stop Tracking
                </button>
              </div>
            </div>
          );
          })}
          {products.length === 0 && (
            <div className="text-center py-10 bg-gray-50 rounded-xl border border-dashed border-gray-300 text-gray-500">
              <span className="text-4xl mb-2 block">🏷️</span>
              You aren't tracking any products yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const components = {
  ConfirmSignUp: {
    Header() {
      return (
        <div className="p-4 text-center">
          <h3 className="text-xl font-bold mb-2">We sent you a code</h3>
          <p className="text-red-500 font-semibold text-sm bg-red-50 p-2 rounded">
            ⚠️ Please check your SPAM/Junk folder if you don't see the email!
          </p>
        </div>
      );
    },
  },
};

export default function AppWithAuth() {
  return (
    <Authenticator components={components}>
      {({ signOut, user }) => <App signOut={signOut} user={user} />}
    </Authenticator>
  );
}
