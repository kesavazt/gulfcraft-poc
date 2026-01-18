import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { sendMessage, getRequests, getUser, downloadFile } from '../api';
import { LogOut, Send, MessageSquare, List, RefreshCw, User, Search, FileText, CheckCircle, Clock, DollarSign, Menu, Download } from 'lucide-react';

export default function Dashboard() {
    const [activeTab, setActiveTab] = useState('chat');
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [requests, setRequests] = useState([]);
    const [user, setUser] = useState(null);
    const [conversationId, setConversationId] = useState(null);
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef(null);
    const navigate = useNavigate();

    useEffect(() => {
        const fetchUser = async () => {
            try {
                const userData = await getUser();
                setUser(userData);
            } catch (error) {
                localStorage.removeItem('token');
                navigate('/login');
            }
        };
        fetchUser();
    }, [navigate]);

    useEffect(() => {
        if (activeTab === 'requests') {
            fetchRequests();
        }
    }, [activeTab]);

    const fetchRequests = async () => {
        try {
            const data = await getRequests();
            setRequests(data);
        } catch (error) {
            console.error("Failed to fetch requests", error);
        }
    };

    const handleSend = async (e) => {
        e.preventDefault();
        if (!input.trim()) return;

        const userMsg = { sender: 'user', content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setLoading(true);

        try {
            const data = await sendMessage(input, conversationId);
            setConversationId(data.conversation_id);
            const aiMsg = {
                sender: 'ai',
                content: data.response,
                download_url: data.download_url,
                similar_quotations: data.state?.similar_quotations
            };
            setMessages(prev => [...prev, aiMsg]);

            // Auto-download costing sheet if available
            if (data.download_url) {
                console.log("Costing sheet available, triggering download:", data.download_url);
                downloadFile(data.download_url);
            }
        } catch (error) {
            console.error("Failed to send message", error);
        } finally {
            setLoading(false);
        }
    };

    const handleSelect = async (quotationId, lineNum) => {
        const selectionMsg = `${quotationId}:${lineNum}`;
        const userMsg = { sender: 'user', content: `Selected: ${quotationId} (Line ${lineNum})` };
        setMessages(prev => [...prev, userMsg]);
        setLoading(true);

        try {
            const data = await sendMessage(selectionMsg, conversationId);
            setConversationId(data.conversation_id);
            const aiMsg = {
                sender: 'ai',
                content: data.response,
                download_url: data.download_url,
                similar_quotations: data.state?.similar_quotations
            };
            setMessages(prev => [...prev, aiMsg]);

            if (data.download_url) {
                downloadFile(data.download_url);
            }
        } catch (error) {
            console.error("Failed to make selection", error);
        } finally {
            setLoading(false);
        }
    };

    const handleLogout = () => {
        localStorage.removeItem('token');
        navigate('/login');
    };

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading]);

    return (
        <div className="min-h-screen bg-gray-50 flex flex-col font-sans">
            {/* Navbar */}
            <nav className="bg-white border-b border-gray-200 sticky top-0 z-30 h-16">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-full">
                    <div className="flex justify-between items-center h-full">
                        <div className="flex items-center gap-3">
                            <img src="/logo.jpg" alt="Gulf Craft" className="h-8 object-contain" />
                            <span className="text-lg font-bold text-brand-900 border-l border-gray-300 pl-3 ml-1">
                                AI Costing Assistant
                            </span>
                        </div>
                        <div className="flex items-center gap-4">
                            <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 rounded-full">
                                <div className="bg-gray-200 p-1 rounded-full">
                                    <User className="h-4 w-4 text-gray-600" />
                                </div>
                                <span className="text-sm font-medium text-gray-700">{user?.username}</span>
                            </div>
                            <button
                                onClick={handleLogout}
                                className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                                title="Sign Out"
                            >
                                <LogOut className="h-5 w-5" />
                            </button>
                        </div>
                    </div>
                </div>
            </nav>

            {/* Main Content */}
            <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <div className="bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden min-h-[700px] flex">

                    {/* Sidebar */}
                    <div className="w-64 bg-gray-50 border-r border-gray-200 flex flex-col pt-6">
                        <div className="px-4 mb-2">
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Menu</h3>
                        </div>
                        <nav className="flex-1 px-2 space-y-1">
                            <button
                                onClick={() => setActiveTab('chat')}
                                className={`w-full flex items-center px-4 py-3 text-sm font-medium rounded-xl transition-all ${activeTab === 'chat'
                                    ? 'bg-brand-50 text-brand-700'
                                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                                    }`}
                            >
                                <MessageSquare className={`mr-3 h-5 w-5 ${activeTab === 'chat' ? 'text-brand-600' : 'text-gray-400'}`} />
                                Chat Assistant
                            </button>
                            <button
                                onClick={() => setActiveTab('requests')}
                                className={`w-full flex items-center px-4 py-3 text-sm font-medium rounded-xl transition-all ${activeTab === 'requests'
                                    ? 'bg-brand-50 text-brand-700'
                                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                                    }`}
                            >
                                <List className={`mr-3 h-5 w-5 ${activeTab === 'requests' ? 'text-brand-600' : 'text-gray-400'}`} />
                                Costing Requests
                            </button>
                        </nav>

                        <div className="p-4 border-t border-gray-200">
                            <div className="bg-brand-900 rounded-xl p-4 text-center">
                                <p className="text-xs text-brand-200 mb-1">Need Help?</p>
                                <p className="text-xs text-white font-medium">Contact IT Support</p>
                            </div>
                        </div>
                    </div>

                    {/* Content Area */}
                    <div className="flex-1 flex flex-col bg-white">
                        {activeTab === 'chat' ? (
                            <div className="h-full flex flex-col">
                                {/* Messages Area */}
                                <div className="flex-1 overflow-y-auto p-8 space-y-6 custom-scrollbar" style={{ maxHeight: '600px' }}>
                                    {messages.length === 0 && (
                                        <div className="flex flex-col items-center justify-center h-full text-gray-400 space-y-4">
                                            <div className="bg-brand-50 p-6 rounded-full">
                                                <img src="/logo.jpg" alt="Gulf Craft" className="h-12 opacity-50 grayscale" />
                                            </div>
                                            <div className="text-center">
                                                <h3 className="text-lg font-semibold text-gray-900">How can I help you today?</h3>
                                                <p className="text-sm text-gray-500 mt-1">Ask about product costing, search items, or check status.</p>
                                            </div>
                                        </div>
                                    )}
                                    {messages.map((msg, idx) => (
                                        <div
                                            key={idx}
                                            className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                                        >
                                            <div
                                                className={`max-w-[80%] rounded-2xl px-6 py-4 shadow-sm ${msg.sender === 'user'
                                                    ? 'bg-brand-600 text-white rounded-br-none'
                                                    : 'bg-gray-50 border border-gray-100 text-gray-800 rounded-bl-none'
                                                    }`}
                                            >
                                                <div className="whitespace-pre-wrap text-sm leading-relaxed">
                                                    {msg.content.split(' ').map((word, i) => {
                                                        if (word.includes('/download/')) {
                                                            const url = `http://localhost:8000${word.replace(/[.,]/g, '')}`;
                                                            return (
                                                                <a
                                                                    key={i}
                                                                    href={url}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    className={`underline font-medium break-all ${msg.sender === 'user'
                                                                        ? 'text-blue-200 hover:text-white'
                                                                        : 'text-brand-600 hover:text-brand-800'
                                                                        }`}
                                                                >
                                                                    {word}{' '}
                                                                </a>
                                                            );
                                                        }
                                                        return word + ' ';
                                                    })}
                                                </div>
                                                {/* Download button for messages with costing sheet */}
                                                {msg.download_url && (
                                                    <button
                                                        onClick={() => downloadFile(msg.download_url)}
                                                        className="mt-3 flex items-center gap-2 px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 transition-all shadow-sm"
                                                    >
                                                        <Download className="h-4 w-4" />
                                                        Download Costing Sheet
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                            
                                            {/* Render Similar Quotations Table */ }
                                            {
                                            msg.similar_quotations && msg.similar_quotations.length > 0 && (
                                                <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm w-full max-w-3xl">
                                                    <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
                                                        <h4 className="text-sm font-semibold text-gray-700">Similar Quotations Found</h4>
                                                    </div>
                                                    <div className="overflow-x-auto">
                                                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                                                            <thead className="bg-gray-50/50">
                                                                <tr>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">ID</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Description</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Model</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Price</th>
                                                                    <th className="px-4 py-2 text-right font-medium text-gray-500">Action</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody className="divide-y divide-gray-200 bg-white">
                                                                {msg.similar_quotations.map((q, qIdx) => (
                                                                    <tr key={qIdx} className="hover:bg-brand-50/30 transition-colors">
                                                                        <td className="px-4 py-3 whitespace-nowrap font-medium text-gray-900">
                                                                            {q.quotation_id}:{q.line_num}
                                                                        </td>
                                                                        <td className="px-4 py-3 text-gray-600 max-w-xs truncate" title={q.description}>
                                                                            {q.description}
                                                                        </td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-500">
                                                                            {q.boat_model}
                                                                        </td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-600">
                                                                            {q.price ? `$${q.price.toFixed(2)}` : '-'}
                                                                        </td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-right">
                                                                            <button
                                                                                onClick={() => handleSelect(q.quotation_id, q.line_num)}
                                                                                className="px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors shadow-sm"
                                                                            >
                                                                                Select
                                                                            </button>
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            )
                                        }
                                        </div>
                                    ))}
                                {loading && (
                                    <div className="flex justify-start">
                                        <div className="bg-gray-50 border border-gray-100 rounded-2xl rounded-bl-none px-6 py-4 shadow-sm">
                                            <div className="flex space-x-2">
                                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-75" />
                                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-150" />
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>

                                {/* Input Area */}
                        <div className="p-6 border-t border-gray-100 bg-white">
                            <form onSubmit={handleSend} className="relative max-w-4xl mx-auto">
                                <input
                                    type="text"
                                    value={input}
                                    onChange={(e) => setInput(e.target.value)}
                                    placeholder="Type your message..."
                                    className="w-full pl-6 pr-14 py-4 bg-gray-50 border border-gray-200 rounded-2xl focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-all outline-none text-gray-700 placeholder-gray-400 shadow-sm"
                                />
                                <button
                                    type="submit"
                                    disabled={!input.trim() || loading}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 p-2.5 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-brand-500/20"
                                >
                                    <Send className="h-5 w-5" />
                                </button>
                            </form>
                        </div>
                    </div>
                    ) : (
                    <div className="h-full flex flex-col p-8">
                        <div className="flex justify-between items-center mb-8">
                            <div>
                                <h3 className="text-2xl font-bold text-gray-900">Active Requests</h3>
                                <p className="text-sm text-gray-500 mt-1">Monitor your costing job status</p>
                            </div>
                            <button
                                onClick={fetchRequests}
                                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-xl transition-all"
                            >
                                <RefreshCw className="h-4 w-4" />
                                Refresh
                            </button>
                        </div>

                        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                            <div className="overflow-x-auto">
                                <table className="min-w-full divide-y divide-gray-200">
                                    <thead className="bg-gray-50">
                                        <tr>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Job ID</th>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Details</th>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Price</th>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Date</th>
                                            <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Download</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-200">
                                        {requests.length === 0 ? (
                                            <tr>
                                                <td colSpan="6" className="px-6 py-12 text-center">
                                                    <div className="flex flex-col items-center justify-center text-gray-400">
                                                        <FileText className="h-12 w-12 mb-3 opacity-20" />
                                                        <p>No requests found.</p>
                                                    </div>
                                                </td>
                                            </tr>
                                        ) : (
                                            requests.map((req) => (
                                                <tr key={req.id} className="hover:bg-gray-50 transition-colors">
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <span className="text-sm font-semibold text-brand-900 bg-brand-50 px-3 py-1 rounded-lg border border-brand-100">
                                                            {req.job_id}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <p className="text-sm text-gray-600 max-w-xs truncate font-medium" title={req.item_details}>
                                                            {req.item_details}
                                                        </p>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${req.status === 'Completed' ? 'bg-green-50 text-green-700 border border-green-200' :
                                                            req.status === 'Awaiting Quote' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' :
                                                                'bg-brand-50 text-brand-700 border border-brand-200'
                                                            }`}>
                                                            {req.status === 'Completed' && <CheckCircle className="h-3 w-3" />}
                                                            {req.status === 'Awaiting Quote' && <Clock className="h-3 w-3" />}
                                                            {req.status}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        {req.price ? (
                                                            <div className="flex items-center text-sm font-bold text-gray-900">
                                                                <DollarSign className="h-3 w-3 text-gray-400 mr-1" />
                                                                {req.price.toFixed(2)}
                                                            </div>
                                                        ) : (
                                                            <span className="text-sm text-gray-400">-</span>
                                                        )}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                        {new Date(req.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                                    </td>
                                                    <td className="px-6 py-4 whitespace-nowrap">
                                                        <button
                                                            onClick={() => downloadFile(`/costing-sheets/by-job/${req.job_id}`)}
                                                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-lg border border-brand-200 transition-all"
                                                            title="Download Costing Sheet"
                                                        >
                                                            <Download className="h-3.5 w-3.5" />
                                                            Download
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                        )}
                </div>
        </div>
            </main >
        </div >
    );
}
