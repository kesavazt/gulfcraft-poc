import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, List, Send, LogOut, User, Download, RefreshCw, CheckCircle, Clock, DollarSign, FileText, X, Edit2, Check, AlertCircle, Trash2, Plus, Search, Paperclip } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendMessage, getRequests, getUser, downloadFile, updateLineItem, approveJob, searchProducts, addLineItem, deleteLineItem, uploadQuotePdf, confirmQuoteMatches } from '../api';

function QuoteMatchCard({ matches, jobId, onConfirm }) {
    const [selections, setSelections] = useState(
        matches.map(m => ({ ...m, apply: m.confidence >= 0.7 }))
    );
    const [confirming, setConfirming] = useState(false);
    const [confirmed, setConfirmed] = useState(false);

    const toggleMatch = (idx) => {
        setSelections(prev => prev.map((s, i) => i === idx ? { ...s, apply: !s.apply } : s));
    };

    const handleConfirm = async () => {
        setConfirming(true);
        await onConfirm(jobId, selections.map(s => ({
            line_item_id: s.line_item_id,
            price: s.ocr_unit_price,
            apply: s.apply
        })));
        setConfirming(false);
        setConfirmed(true);
    };

    if (confirmed) {
        return (
            <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-xl">
                <p className="text-green-700 font-medium text-sm">Quotes applied successfully!</p>
            </div>
        );
    }

    return (
        <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm w-full max-w-3xl">
            <div className="px-4 py-3 bg-blue-50 border-b border-blue-100">
                <h4 className="text-sm font-semibold text-blue-800">Review Matched Quote Items</h4>
                <p className="text-xs text-blue-600 mt-1">Select which prices to apply from the vendor quote</p>
            </div>
            <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-3 py-2 text-center w-10">Apply</th>
                            <th className="px-3 py-2 text-left">Vendor Item</th>
                            <th className="px-3 py-2 text-left">Matched To</th>
                            <th className="px-3 py-2 text-right">Price (AED)</th>
                            <th className="px-3 py-2 text-center">Confidence</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {selections.map((match, idx) => (
                            <tr key={idx} className="hover:bg-gray-50/50">
                                <td className="px-3 py-2 text-center">
                                    <input
                                        type="checkbox"
                                        checked={match.apply}
                                        onChange={() => toggleMatch(idx)}
                                        className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                                    />
                                </td>
                                <td className="px-3 py-2 text-gray-600">{match.ocr_item_name}</td>
                                <td className="px-3 py-2 font-medium text-gray-900">{match.pending_item_name}</td>
                                <td className="px-3 py-2 text-right font-bold">{match.ocr_unit_price?.toFixed(2)}</td>
                                <td className="px-3 py-2 text-center">
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${match.confidence >= 0.9 ? 'bg-green-100 text-green-700' :
                                            match.confidence >= 0.7 ? 'bg-yellow-100 text-yellow-700' :
                                                'bg-red-100 text-red-700'
                                        }`}>
                                        {(match.confidence * 100).toFixed(0)}%
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="px-4 py-3 bg-gray-50 flex justify-end gap-2 border-t border-gray-100">
                <button
                    onClick={handleConfirm}
                    disabled={confirming || !selections.some(s => s.apply)}
                    className="px-6 py-2 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-700 disabled:opacity-50 transition-all shadow-sm"
                >
                    {confirming ? 'Applying...' : `Apply ${selections.filter(s => s.apply).length} Price(s)`}
                </button>
            </div>
        </div>
    );
}

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
    const [agentState, setAgentState] = useState(null);
    const [selectedJob, setSelectedJob] = useState(null);
    const [editingItemId, setEditingItemId] = useState(null);
    const [editValue, setEditValue] = useState('');
    const [editType, setEditType] = useState('price'); // 'price', 'quantity', 'name', 'code'
    const [actionLoading, setActionLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const fileInputRef = useRef(null);
    const [uploadLoading, setUploadLoading] = useState(false);
    const [showUploadModal, setShowUploadModal] = useState(false);
    const [uploadJobId, setUploadJobId] = useState('');
    const [uploadFile, setUploadFile] = useState(null);

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
        if (e) e.preventDefault();
        if (!input.trim() || loading) return;

        const userMsg = { sender: 'user', content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setLoading(true);

        try {
            const data = await sendMessage(input, conversationId, agentState);
            setConversationId(data.conversation_id);
            setAgentState(data.state);
            const aiMsg = {
                sender: 'ai',
                content: data.response,
                download_url: data.download_url,
                similar_quotations: data.state?.similar_quotations,
                pending_products: (data.state?.pending_disambiguation?.agent === 'pricing_advisor' ||
                                  data.state?.pending_disambiguation?.agent === 'edit_job')
                    ? data.state.pending_disambiguation.items
                    : null
            };
            setMessages(prev => [...prev, aiMsg]);
        } catch (error) {
            console.error("Failed to send message", error);
        } finally {
            setLoading(false);
        }
    };

    const handleFileSelected = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            setMessages(prev => [...prev, { sender: 'ai', content: 'Please select a PDF file.' }]);
            return;
        }
        setUploadFile(file);
        const currentJobId = agentState?.last_mentioned_job_id || agentState?.job_id;
        if (currentJobId) {
            setUploadJobId(currentJobId);
            handleUploadQuote(file, currentJobId);
        } else {
            setShowUploadModal(true);
        }
        e.target.value = '';
    };

    const handleUploadQuote = async (file, jobId) => {
        setUploadLoading(true);
        setMessages(prev => [...prev, { sender: 'user', content: `Uploading vendor quote: ${file.name} for job ${jobId}` }]);

        try {
            const result = await uploadQuotePdf(file, jobId, conversationId);
            if (result.matches && result.matches.length > 0) {
                setMessages(prev => [...prev, {
                    sender: 'ai',
                    content: `Extracted **${result.extracted_count}** items from the PDF and matched **${result.matches.length}** to pending quotes for job **${jobId}**. Review the matches below and confirm which prices to apply.`,
                    quoteMatches: result
                }]);
            } else {
                setMessages(prev => [...prev, {
                    sender: 'ai',
                    content: result.message || 'No matching items found in the uploaded PDF.'
                }]);
            }
        } catch (error) {
            console.error('Upload failed:', error);
            setMessages(prev => [...prev, { sender: 'ai', content: 'Failed to process the uploaded PDF. Please try again.' }]);
        } finally {
            setUploadLoading(false);
            setUploadFile(null);
        }
    };

    const handleConfirmMatches = async (jobId, matchSelections) => {
        try {
            const result = await confirmQuoteMatches(jobId, matchSelections);
            let msg = `Applied **${result.applied_count}** quote price(s) to job **${jobId}**.`;
            if (result.all_quotes_received) {
                msg += '\n\nAll quotes received! Job is now ready for review.';
            } else if (result.pending_items?.length > 0) {
                msg += `\n\nStill waiting for ${result.pending_items.length} quote(s).`;
            }
            setMessages(prev => [...prev, {
                sender: 'ai',
                content: msg,
                download_url: result.download_url
            }]);
            fetchRequests();
        } catch (error) {
            console.error('Confirm failed:', error);
            setMessages(prev => [...prev, { sender: 'ai', content: 'Failed to apply quotes. Please try again.' }]);
        }
    };

    const handleSelect = async (quotationId, lineNum) => {
        const selectionMsg = `${quotationId}:${lineNum}`;
        const userMsg = { sender: 'user', content: `Selected: ${quotationId} (Line ${lineNum})` };
        setMessages(prev => [...prev, userMsg]);
        setLoading(true);

        try {
            const data = await sendMessage(selectionMsg, conversationId, agentState);
            setConversationId(data.conversation_id);
            setAgentState(data.state);
            const aiMsg = {
                sender: 'ai',
                content: data.response,
                download_url: data.download_url,
                similar_quotations: data.state?.similar_quotations,
                pending_products: (data.state?.pending_disambiguation?.agent === 'pricing_advisor' ||
                                  data.state?.pending_disambiguation?.agent === 'edit_job')
                    ? data.state.pending_disambiguation.items
                    : null
            };
            setMessages(prev => [...prev, aiMsg]);
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

    const handleUpdateItem = async (jobId, itemId, field, value) => {
        try {
            setActionLoading(true);
            const data = {};
            if (field === 'price') data.unit_price = parseFloat(value);
            if (field === 'quantity') data.quantity = parseInt(value);
            if (field === 'name') data.item_name = value;
            if (field === 'code') data.item_code = value;
            if (field === 'margin') data.margin = 1 + (parseFloat(value) / 100);

            const updatedItem = await updateLineItem(jobId, itemId, data);

            // Update local state for immediate feedback
            const updatedRequests = requests.map(req => {
                if (req.job_id === jobId) {
                    const updatedItems = req.line_items.map(item =>
                        item.id === itemId ? updatedItem : item
                    );
                    const newTotal = updatedItems.reduce((acc, item) => acc + (item.unit_price || 0) * (item.quantity || 1), 0);
                    return { ...req, line_items: updatedItems, price: newTotal };
                }
                return req;
            });
            setRequests(updatedRequests);
            if (selectedJob?.job_id === jobId) {
                const refreshedJob = updatedRequests.find(r => r.job_id === jobId);
                setSelectedJob(refreshedJob);
            }

            setEditingItemId(null);
        } catch (error) {
            console.error('Update failed:', error);
            alert('Failed to update item.');
        } finally {
            setActionLoading(false);
        }
    };

    const handleSearchProducts = async (query) => {
        setSearchQuery(query);
        if (query.length < 2) {
            setSearchResults([]);
            return;
        }
        try {
            setSearchLoading(true);
            const results = await searchProducts(query);
            setSearchResults(results);
        } catch (error) {
            console.error('Search failed:', error);
        } finally {
            setSearchLoading(false);
        }
    };

    const handleAddItem = async (jobId, product = null) => {
        try {
            setActionLoading(true);
            const itemData = product ? {
                item_name: product.item_name,
                item_code: product.item_code,
                unit_price: product.unit_cost,
                item_type: 'Item',
                vendor_email: product.vendor_email
            } : {
                item_name: 'New Custom Item',
                quantity: 1,
                item_type: 'Item'
            };

            const newItem = await addLineItem(jobId, itemData);

            const updatedRequests = requests.map(req => {
                if (req.job_id === jobId) {
                    const updatedItems = [...(req.line_items || []), newItem];
                    const newTotal = updatedItems.reduce((acc, item) => acc + (item.unit_price || 0) * (item.quantity || 1), 0);
                    return { ...req, line_items: updatedItems, price: newTotal };
                }
                return req;
            });
            setRequests(updatedRequests);
            if (selectedJob?.job_id === jobId) {
                const refreshedJob = updatedRequests.find(r => r.job_id === jobId);
                setSelectedJob(refreshedJob);
            }

            setSearchQuery('');
            setSearchResults([]);
        } catch (error) {
            console.error('Add failed:', error);
            alert('Failed to add item.');
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeleteItem = async (jobId, itemId) => {
        if (!confirm('Are you sure you want to remove this item?')) return;
        try {
            setActionLoading(true);
            await deleteLineItem(jobId, itemId);

            const updatedRequests = requests.map(req => {
                if (req.job_id === jobId) {
                    const updatedItems = req.line_items.filter(i => i.id !== itemId);
                    const newTotal = updatedItems.reduce((acc, item) => acc + (item.unit_price || 0) * (item.quantity || 1), 0);
                    return { ...req, line_items: updatedItems, price: newTotal };
                }
                return req;
            });
            setRequests(updatedRequests);
            if (selectedJob?.job_id === jobId) {
                const refreshedJob = updatedRequests.find(r => r.job_id === jobId);
                setSelectedJob(refreshedJob);
            }
        } catch (error) {
            console.error('Delete failed:', error);
            alert('Failed to delete item.');
        } finally {
            setActionLoading(false);
        }
    };

    const handleApprove = async (jobId) => {
        if (!window.confirm("Are you sure you want to approve this job and send the completion email?")) return;
        setActionLoading(true);
        try {
            await approveJob(jobId);
            const updatedRequests = requests.map(req =>
                req.job_id === jobId ? { ...req, status: 'Approved' } : req
            );
            setRequests(updatedRequests);
            if (selectedJob?.job_id === jobId) {
                setSelectedJob({ ...selectedJob, status: 'Approved' });
            }
            alert("Job approved and email sent!");
        } catch (error) {
            console.error("Failed to approve job", error);
        } finally {
            setActionLoading(false);
        }
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
                    <div className="flex-1 flex flex-col bg-white min-w-0">
                        {activeTab === 'chat' ? (
                            <div className="h-full flex flex-col">
                                {/* Messages Area */}
                                <div className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-4 sm:space-y-6 custom-scrollbar" style={{ maxHeight: '600px' }}>
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
                                        <div key={idx} className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}>
                                            <div className={`max-w-[80%] rounded-2xl px-6 py-4 shadow-sm ${msg.sender === 'user' ? 'bg-brand-600 text-white rounded-br-none' : 'bg-gray-50 border border-gray-100 text-gray-800 rounded-bl-none'}`}>
                                                <div className="markdown-content text-sm leading-relaxed overflow-x-auto">
                                                    <ReactMarkdown
                                                        remarkPlugins={[remarkGfm]}
                                                        components={{
                                                            a: ({ node, ...props }) => (
                                                                <a
                                                                    {...props}
                                                                    target="_blank"
                                                                    rel="noopener noreferrer"
                                                                    className={`underline font-medium break-all ${msg.sender === 'user' ? 'text-blue-200 hover:text-white' : 'text-brand-600 hover:text-brand-800'}`}
                                                                />
                                                            ),
                                                            table: ({ node, ...props }) => (
                                                                <div className="my-4 overflow-x-auto border border-gray-200 rounded-lg">
                                                                    <table {...props} className="min-w-full divide-y divide-gray-200" />
                                                                </div>
                                                            ),
                                                            thead: ({ node, ...props }) => <thead {...props} className="bg-gray-100" />,
                                                            th: ({ node, ...props }) => <th {...props} className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider border-b" />,
                                                            td: ({ node, ...props }) => <td {...props} className="px-4 py-2 border-b text-gray-700" />,
                                                            tr: ({ node, ...props }) => <tr {...props} className="hover:bg-gray-50/50 transition-colors" />
                                                        }}
                                                    >
                                                        {msg.content}
                                                    </ReactMarkdown>
                                                </div>

                                                {msg.download_url && (
                                                    <button onClick={() => downloadFile(msg.download_url)} className="mt-3 flex items-center gap-2 px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 transition-all shadow-sm">
                                                        <Download className="h-4 w-4" /> Download Costing Sheet
                                                    </button>
                                                )}
                                            </div>

                                            {msg.quoteMatches && msg.quoteMatches.matches?.length > 0 && (
                                                <QuoteMatchCard
                                                    matches={msg.quoteMatches.matches}
                                                    jobId={msg.quoteMatches.job_id}
                                                    onConfirm={handleConfirmMatches}
                                                />
                                            )}

                                            {msg.similar_quotations && msg.similar_quotations.length > 0 && (
                                                <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm w-full max-w-3xl">
                                                    <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
                                                        <h4 className="text-sm font-semibold text-gray-700">Similar Quotations Found</h4>
                                                    </div>
                                                    <div className="overflow-x-auto">
                                                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                                                            <thead className="bg-gray-50/50">
                                                                <tr>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">#</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Quotation ID</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Description</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Model</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Price</th>
                                                                    <th className="px-4 py-2 text-right font-medium text-gray-500">Action</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody className="divide-y divide-gray-200 bg-white">
                                                                {msg.similar_quotations.map((q, qIdx) => (
                                                                    <tr key={qIdx} className="hover:bg-brand-50/30 transition-colors">
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-500">{qIdx + 1}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap font-medium text-gray-900">{q.quotation_id}:{q.line_num}</td>
                                                                        <td className="px-4 py-3 text-gray-600 max-w-xs truncate" title={q.description}>{q.description}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-500">{q.boat_model}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-600">{q.price ? `${q.price.toLocaleString()} AED` : '-'}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-right">
                                                                            <button onClick={() => handleSelect(q.quotation_id, q.line_num)} className="px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors shadow-sm">Select</button>
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            )}

                                            {msg.pending_products && msg.pending_products.length > 0 && (
                                                <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm w-full max-w-3xl">
                                                    <div className="px-4 py-3 bg-blue-50 border-b border-blue-100">
                                                        <h4 className="text-sm font-semibold text-blue-800">Product Search Results</h4>
                                                    </div>
                                                    <div className="overflow-x-auto">
                                                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                                                            <thead className="bg-gray-50/50">
                                                                <tr>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">#</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Item Name</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Item Code</th>
                                                                    <th className="px-4 py-2 text-right font-medium text-gray-500">Unit Cost</th>
                                                                    <th className="px-4 py-2 text-left font-medium text-gray-500">Vendor</th>
                                                                    <th className="px-4 py-2 text-right font-medium text-gray-500">Action</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody className="divide-y divide-gray-200 bg-white">
                                                                {msg.pending_products.map((product, pIdx) => (
                                                                    <tr key={pIdx} className="hover:bg-blue-50/30 transition-colors">
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-500">{pIdx + 1}</td>
                                                                        <td className="px-4 py-3 text-gray-900 font-medium max-w-xs truncate" title={product.item_name}>{product.item_name || 'Unknown'}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap font-mono text-xs text-gray-600">{product.item_code || 'N/A'}</td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-right font-bold text-gray-900">
                                                                            {product.unit_cost ? `${product.unit_cost.toLocaleString()} AED` : 'N/A'}
                                                                        </td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-gray-500">
                                                                            {product.vendor_email ? product.vendor_email.split('@')[0] : 'N/A'}
                                                                        </td>
                                                                        <td className="px-4 py-3 whitespace-nowrap text-right">
                                                                            <button
                                                                                onClick={() => {
                                                                                    const selectionMsg = { sender: 'user', content: `${pIdx + 1}` };
                                                                                    setMessages(prev => [...prev, selectionMsg]);
                                                                                    setLoading(true);
                                                                                    sendMessage(`${pIdx + 1}`, conversationId, agentState)
                                                                                        .then(data => {
                                                                                            setConversationId(data.conversation_id);
                                                                                            setAgentState(data.state);
                                                                                            const aiMsg = {
                                                                                                sender: 'ai',
                                                                                                content: data.response,
                                                                                                download_url: data.download_url
                                                                                            };
                                                                                            setMessages(prev => [...prev, aiMsg]);
                                                                                        })
                                                                                        .catch(err => console.error("Selection failed", err))
                                                                                        .finally(() => setLoading(false));
                                                                                }}
                                                                                className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
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
                                            )}
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
                                <div className="p-4 sm:p-6 border-t border-gray-100 bg-white">
                                    <form onSubmit={handleSend} className="relative max-w-4xl mx-auto">
                                        <input
                                            type="file"
                                            ref={fileInputRef}
                                            accept=".pdf"
                                            className="hidden"
                                            onChange={handleFileSelected}
                                        />
                                        <input
                                            type="text"
                                            value={input}
                                            onChange={(e) => setInput(e.target.value)}
                                            placeholder="Type your message..."
                                            className="w-full pl-6 pr-24 py-4 bg-gray-50 border border-gray-200 rounded-2xl focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-all outline-none text-gray-700 placeholder-gray-400 shadow-sm"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => fileInputRef.current?.click()}
                                            disabled={uploadLoading}
                                            className="absolute right-14 top-1/2 -translate-y-1/2 p-2.5 text-gray-400 hover:text-brand-600 rounded-xl transition-all disabled:opacity-50"
                                            title="Upload vendor quote PDF"
                                        >
                                            {uploadLoading ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Paperclip className="h-5 w-5" />}
                                        </button>
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
                            <div className="h-full flex flex-col p-4 sm:p-6 lg:p-8">
                                <div className="flex flex-wrap justify-between items-center gap-4 mb-6 sm:mb-8">
                                    <div className="min-w-0 flex-1">
                                        <h3 className="text-xl sm:text-2xl font-bold text-gray-900">Active Requests</h3>
                                        <p className="text-sm text-gray-500 mt-1">Monitor your costing job status</p>
                                    </div>
                                    <button
                                        onClick={fetchRequests}
                                        className="flex-shrink-0 flex items-center gap-2 px-4 py-2 text-sm font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-xl transition-all whitespace-nowrap"
                                    >
                                        <RefreshCw className="h-4 w-4" />
                                        Refresh
                                    </button>
                                </div>

                                <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
                                    <div className="overflow-x-auto">
                                        <table className="min-w-[900px] w-full divide-y divide-gray-200">
                                            <thead className="bg-gray-50">
                                                <tr>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider" style={{ minWidth: '140px' }}>Job ID</th>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Details</th>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider" style={{ minWidth: '150px' }}>Status</th>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider" style={{ minWidth: '130px' }}>Price</th>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider" style={{ minWidth: '100px' }}>Date</th>
                                                    <th className="px-4 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider" style={{ minWidth: '160px' }}>Download</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-gray-200">
                                                {requests.length === 0 ? (
                                                    <tr>
                                                        <td colSpan="6" className="px-4 py-12 text-center">
                                                            <div className="flex flex-col items-center justify-center text-gray-400">
                                                                <FileText className="h-12 w-12 mb-3 opacity-20" />
                                                                <p>No requests found.</p>
                                                            </div>
                                                        </td>
                                                    </tr>
                                                ) : (
                                                    requests.map((req) => (
                                                        <tr key={req.id}
                                                            onClick={() => setSelectedJob(req)}
                                                            className="hover:bg-gray-50 transition-colors cursor-pointer"
                                                        >
                                                            <td className="px-4 py-4 whitespace-nowrap">
                                                                <span className="text-sm font-semibold text-brand-900 bg-brand-50 px-3 py-1 rounded-lg border border-brand-100">
                                                                    {req.job_id}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-4">
                                                                <p className="text-sm text-gray-600 max-w-xs truncate font-medium" title={req.item_details}>
                                                                    {req.item_details}
                                                                </p>
                                                            </td>
                                                            <td className="px-4 py-4 whitespace-nowrap">
                                                                <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${req.status === 'Approved' ? 'bg-blue-50 text-blue-700 border border-blue-200' :
                                                                    req.status === 'Completed' ? 'bg-green-50 text-green-700 border border-green-200' :
                                                                        req.status === 'Awaiting Quote' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' :
                                                                            'bg-brand-50 text-brand-700 border border-brand-200'
                                                                    }`}>
                                                                    {req.status === 'Approved' && <CheckCircle className="h-3 w-3" />}
                                                                    {req.status === 'Completed' && <CheckCircle className="h-3 w-3" />}
                                                                    {req.status === 'Awaiting Quote' && <Clock className="h-3 w-3" />}
                                                                    {req.status}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-4 whitespace-nowrap">
                                                                {req.price ? (
                                                                    <div className="text-sm font-bold text-gray-900">
                                                                        {req.price.toFixed(2)} AED
                                                                    </div>
                                                                ) : (
                                                                    <span className="text-sm text-gray-400">-</span>
                                                                )}
                                                            </td>
                                                            <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                                                                {new Date(req.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                                            </td>
                                                            <td className="px-4 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                                                                <button
                                                                    onClick={() => downloadFile(`/costing-sheets/by-job/${req.job_id}`)}
                                                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-700 bg-brand-50 hover:bg-brand-100 rounded-lg border border-brand-200 transition-all whitespace-nowrap"
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
            </main>

            {/* Job Details Modal */}
            {selectedJob && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm animate-in fade-in duration-200">
                    <div className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col scale-in duration-200">
                        {/* Modal Header */}
                        <div className="px-4 sm:px-6 py-4 border-b border-gray-100 flex flex-wrap justify-between items-start gap-4 bg-gray-50/50">
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-3 flex-wrap">
                                    <h3 className="text-lg sm:text-xl font-bold text-gray-900">Job: {selectedJob.job_id}</h3>
                                    <span className={`px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider whitespace-nowrap ${selectedJob.status === 'Approved' ? 'bg-blue-100 text-blue-700' : 'bg-brand-100 text-brand-700'
                                        }`}>
                                        {selectedJob.status}
                                    </span>
                                </div>
                                <p className="text-sm text-gray-500 mt-1 break-words">{selectedJob.item_details}</p>
                            </div>
                            <button
                                onClick={() => setSelectedJob(null)}
                                className="flex-shrink-0 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-all"
                            >
                                <X className="h-6 w-6" />
                            </button>
                        </div>

                        {/* Modal Body */}
                        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6">
                            {/* Product Search and Add Custom Item */}
                            <div className="flex flex-col sm:flex-row gap-4 items-start">
                                <div className="relative flex-1 w-full">
                                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                        <Search className="h-4 w-4 text-gray-400" />
                                    </div>
                                    <input
                                        type="text"
                                        value={searchQuery}
                                        onChange={(e) => handleSearchProducts(e.target.value)}
                                        placeholder="Search products by code..."
                                        className="block w-full pl-10 pr-3 py-2 border border-gray-200 rounded-xl leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 sm:text-sm transition-all shadow-sm"
                                    />
                                    {searchResults.length > 0 && (
                                        <div className="absolute z-10 mt-1 w-full bg-white shadow-xl max-h-60 rounded-xl py-1 text-base ring-1 ring-black ring-opacity-5 overflow-auto focus:outline-none sm:text-sm border border-gray-100 animate-in fade-in slide-in-from-top-1">
                                            {searchResults.map((product, idx) => (
                                                <button
                                                    key={idx}
                                                    onClick={() => handleAddItem(selectedJob.job_id, product)}
                                                    className="w-full text-left cursor-pointer hover:bg-brand-50 px-4 py-3 transition-colors border-b last:border-0 border-gray-50"
                                                >
                                                    <div className="flex justify-between items-start gap-2">
                                                        <div className="flex-1 min-w-0">
                                                            <div className="font-semibold text-gray-900 truncate">{product.item_name}</div>
                                                            <div className="text-xs text-gray-500 mt-0.5 font-mono">{product.item_code || 'No code'}</div>
                                                        </div>
                                                        <div className="text-brand-600 font-bold whitespace-nowrap">{product.unit_cost?.toLocaleString() || '0'} AED</div>
                                                    </div>
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    {searchLoading && (
                                        <div className="absolute right-3 top-2.5">
                                            <RefreshCw className="h-4 w-4 text-brand-500 animate-spin" />
                                        </div>
                                    )}
                                </div>
                                <button
                                    onClick={() => handleAddItem(selectedJob.job_id)}
                                    className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-2 bg-white border-2 border-brand-100 text-brand-700 text-sm font-bold rounded-xl hover:bg-brand-50 hover:border-brand-200 transition-all shadow-sm"
                                >
                                    <Plus className="h-4 w-4" />
                                    Custom Item
                                </button>
                            </div>

                            <div>
                                <h4 className="text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">Line Items</h4>
                                <div className="border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                                    <div className="overflow-x-auto">
                                        <table className="min-w-[1100px] w-full divide-y divide-gray-200 text-sm">
                                            <thead className="bg-gray-50">
                                                <tr>
                                                    <th className="px-4 py-3 text-left font-semibold text-gray-500">Item</th>
                                                    <th className="px-4 py-3 text-left font-semibold text-gray-500">Code</th>
                                                    <th className="px-3 py-3 text-center font-semibold text-gray-500 text-xs" style={{ width: '70px' }}>Est. Qty</th>
                                                    <th className="px-3 py-3 text-right font-semibold text-gray-500 text-xs" style={{ width: '90px' }}>Est. Price</th>
                                                    <th className="px-3 py-3 text-center font-semibold text-gray-500" style={{ width: '70px' }}>Qty</th>
                                                    <th className="px-3 py-3 text-right font-semibold text-gray-500 text-xs" style={{ width: '95px' }}>Products Price</th>
                                                    <th className="px-3 py-3 text-right font-semibold text-gray-500">Unit Price</th>
                                                    <th className="px-3 py-3 text-center font-semibold text-gray-500 text-xs" style={{ width: '80px' }}>Margin %</th>
                                                    <th className="px-3 py-3 text-center font-semibold text-gray-500 text-xs" style={{ width: '90px' }}>Source</th>
                                                    <th className="px-3 py-3 text-center font-semibold text-gray-500 text-xs">Status</th>
                                                    <th className="px-3 py-3 text-right font-semibold text-gray-500" style={{ width: '50px' }}></th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-gray-200 bg-white">
                                                {selectedJob.line_items?.slice().sort((a, b) => {
                                                    const aLabour = (a.item_type || '').toLowerCase() === 'hour' ? 1 : 0;
                                                    const bLabour = (b.item_type || '').toLowerCase() === 'hour' ? 1 : 0;
                                                    return aLabour - bLabour;
                                                }).map((item) => (
                                                    <tr key={item.id} className="hover:bg-gray-50/50 group">
                                                        {/* Item Name */}
                                                        <td className="px-4 py-3">
                                                            {editingItemId === item.id && editType === 'name' ? (
                                                                <div className="flex items-center gap-1">
                                                                    <input
                                                                        type="text"
                                                                        value={editValue}
                                                                        onChange={(e) => setEditValue(e.target.value)}
                                                                        className="w-full px-2 py-1 border border-brand-500 rounded outline-none"
                                                                        autoFocus
                                                                    />
                                                                    <button onClick={() => handleUpdateItem(selectedJob.job_id, item.id, 'name', editValue)} className="p-1 bg-green-500 text-white rounded"><Check className="h-4 w-4" /></button>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-between gap-1 group/item">
                                                                    <span className="font-medium text-gray-900">{item.item_name}</span>
                                                                    <button onClick={() => { setEditingItemId(item.id); setEditType('name'); setEditValue(item.item_name); }} className="p-1 text-gray-300 hover:text-brand-500 opacity-0 group-hover/item:opacity-100 transition-all"><Edit2 className="h-3 w-3" /></button>
                                                                </div>
                                                            )}
                                                        </td>
                                                        {/* Item Code */}
                                                        <td className="px-4 py-3">
                                                            {editingItemId === item.id && editType === 'code' ? (
                                                                <div className="flex items-center gap-1">
                                                                    <input
                                                                        type="text"
                                                                        value={editValue}
                                                                        onChange={(e) => setEditValue(e.target.value)}
                                                                        className="w-full px-2 py-1 border border-brand-500 rounded outline-none font-mono text-xs"
                                                                        autoFocus
                                                                    />
                                                                    <button onClick={() => handleUpdateItem(selectedJob.job_id, item.id, 'code', editValue)} className="p-1 bg-green-500 text-white rounded"><Check className="h-4 w-4" /></button>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-between gap-1 group/item">
                                                                    <span className="text-gray-500 font-mono text-xs">{item.item_code || '-'}</span>
                                                                    <button onClick={() => { setEditingItemId(item.id); setEditType('code'); setEditValue(item.item_code || ''); }} className="p-1 text-gray-300 hover:text-brand-500 opacity-0 group-hover/item:opacity-100 transition-all"><Edit2 className="h-3 w-3" /></button>
                                                                </div>
                                                            )}
                                                        </td>
                                                        {/* Estimation Quantity */}
                                                        <td className="px-3 py-3 text-center">
                                                            <span className="text-gray-500 text-xs" title="Quantity from estimation">
                                                                {item.estimation_quantity ?? '-'}
                                                            </span>
                                                        </td>
                                                        {/* Estimation Price */}
                                                        <td className="px-3 py-3 text-right">
                                                            <span className="text-gray-500 text-xs" title="Last purchase price from estimation">
                                                                {item.estimation_last_purchase_price ? item.estimation_last_purchase_price.toFixed(2) : (item.estimation_average_price ? item.estimation_average_price.toFixed(2) : '-')}
                                                            </span>
                                                        </td>
                                                        {/* Current Quantity (editable) */}
                                                        <td className="px-3 py-3 text-center">
                                                            {editingItemId === item.id && editType === 'quantity' ? (
                                                                <div className="flex items-center gap-1">
                                                                    <input
                                                                        type="number"
                                                                        value={editValue}
                                                                        onChange={(e) => setEditValue(e.target.value)}
                                                                        className="w-16 px-1 py-1 border border-brand-500 rounded text-center outline-none"
                                                                        autoFocus
                                                                    />
                                                                    <button onClick={() => handleUpdateItem(selectedJob.job_id, item.id, 'quantity', editValue)} className="p-1 bg-green-500 text-white rounded"><Check className="h-4 w-4" /></button>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-center gap-1 group/item">
                                                                    <span className="text-gray-900 font-medium">{item.quantity}</span>
                                                                    <button onClick={() => { setEditingItemId(item.id); setEditType('quantity'); setEditValue(item.quantity.toString()); }} className="p-1 text-gray-300 hover:text-brand-500 opacity-0 group-hover/item:opacity-100 transition-all"><Edit2 className="h-3 w-3" /></button>
                                                                </div>
                                                            )}
                                                        </td>
                                                        {/* Products Table Price */}
                                                        <td className="px-3 py-3 text-right">
                                                            <span className="text-gray-600 text-xs" title="Price from products table lookup">
                                                                {item.products_table_price ? item.products_table_price.toFixed(2) : '-'}
                                                            </span>
                                                        </td>
                                                        {/* Unit Price (editable) */}
                                                        <td className="px-3 py-3 text-right">
                                                            {editingItemId === item.id && editType === 'price' ? (
                                                                <div className="flex items-center justify-end gap-1">
                                                                    <input
                                                                        type="number"
                                                                        value={editValue}
                                                                        onChange={(e) => setEditValue(e.target.value)}
                                                                        className="w-24 px-2 py-1 border border-brand-500 rounded text-right outline-none"
                                                                        autoFocus
                                                                    />
                                                                    <button onClick={() => handleUpdateItem(selectedJob.job_id, item.id, 'price', editValue)} className="p-1 bg-green-500 text-white rounded"><Check className="h-4 w-4" /></button>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-end gap-1 group/item">
                                                                    <span className="font-bold text-gray-900">
                                                                        {item.unit_price ? item.unit_price.toFixed(2) : '0.00'}
                                                                    </span>
                                                                    <button onClick={() => { setEditingItemId(item.id); setEditType('price'); setEditValue(item.unit_price?.toString() || '0'); }} className="p-1 text-gray-300 hover:text-brand-500 opacity-0 group-hover/item:opacity-100 transition-all"><Edit2 className="h-3 w-3" /></button>
                                                                </div>
                                                            )}
                                                        </td>
                                                        {/* Margin % (editable) */}
                                                        <td className="px-3 py-3 text-center">
                                                            {editingItemId === item.id && editType === 'margin' ? (
                                                                <div className="flex items-center gap-1">
                                                                    <input
                                                                        type="number"
                                                                        value={editValue}
                                                                        onChange={(e) => setEditValue(e.target.value)}
                                                                        className="w-16 px-1 py-1 border border-brand-500 rounded text-center outline-none"
                                                                        autoFocus
                                                                    />
                                                                    <button onClick={() => handleUpdateItem(selectedJob.job_id, item.id, 'margin', editValue)} className="p-1 bg-green-500 text-white rounded"><Check className="h-4 w-4" /></button>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-center gap-1 group/item">
                                                                    <span className="text-orange-600 font-medium text-xs">
                                                                        {item.margin ? ((item.margin - 1) * 100).toFixed(0) : '50'}%
                                                                    </span>
                                                                    <button onClick={() => { setEditingItemId(item.id); setEditType('margin'); setEditValue(item.margin ? ((item.margin - 1) * 100).toFixed(0) : '50'); }} className="p-1 text-gray-300 hover:text-brand-500 opacity-0 group-hover/item:opacity-100 transition-all"><Edit2 className="h-3 w-3" /></button>
                                                                </div>
                                                            )}
                                                        </td>
                                                        {/* Price Source */}
                                                        <td className="px-3 py-3 text-center">
                                                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase whitespace-nowrap ${item.price_source === 'products' ? 'bg-blue-100 text-blue-700' :
                                                                    item.price_source === 'quotation' ? 'bg-purple-100 text-purple-700' :
                                                                        item.price_source === 'manual' ? 'bg-orange-100 text-orange-700' :
                                                                            item.price_source === 'labour' ? 'bg-indigo-100 text-indigo-700' :
                                                                                'bg-gray-100 text-gray-700'
                                                                }`}>
                                                                {item.price_source || 'N/A'}
                                                            </span>
                                                        </td>
                                                        {/* Status */}
                                                        <td className="px-3 py-3 text-center">
                                                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${item.price_status === 'resolved' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                                                                }`}>
                                                                {item.price_status}
                                                            </span>
                                                        </td>
                                                        {/* Delete Button */}
                                                        <td className="px-3 py-3 text-right">
                                                            <button
                                                                onClick={() => handleDeleteItem(selectedJob.job_id, item.id)}
                                                                className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded transition-all opacity-0 group-hover:opacity-100"
                                                            >
                                                                <Trash2 className="h-4 w-4" />
                                                            </button>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                            <tfoot className="bg-gray-50/50 font-bold">
                                                <tr>
                                                    <td colSpan="6" className="px-4 py-4 text-right text-gray-500 uppercase tracking-wider text-xs">Total Estimated Cost</td>
                                                    <td className="px-3 py-4 text-right text-brand-900 text-lg">
                                                        {(selectedJob.line_items?.reduce((acc, item) => acc + (item.unit_price || 0) * (item.quantity || 1), 0) || 0).toFixed(2)} AED
                                                    </td>
                                                    <td colSpan="4"></td>
                                                </tr>
                                            </tfoot>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Modal Footer */}
                        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 flex justify-between items-center">
                            <div className="flex items-center gap-2 text-gray-500 text-sm">
                                <AlertCircle className="h-4 w-4" />
                                <span>Approval sends the final costing sheet to IT Support.</span>
                            </div>
                            <div className="flex gap-3">
                                <button
                                    onClick={() => setSelectedJob(null)}
                                    className="px-6 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-200 rounded-xl transition-all"
                                >
                                    Close
                                </button>
                                {selectedJob.status !== 'Approved' && (
                                    <button
                                        onClick={() => handleApprove(selectedJob.job_id)}
                                        disabled={actionLoading}
                                        className="flex items-center gap-2 px-8 py-2 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-700 shadow-lg shadow-brand-500/20 transition-all disabled:opacity-50"
                                    >
                                        {actionLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4" />}
                                        Approve & Send Email
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
            {/* Upload Job ID Modal */}
            {showUploadModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
                        <h3 className="text-lg font-bold text-gray-900 mb-2">Upload Vendor Quote</h3>
                        <p className="text-sm text-gray-500 mb-4">Which job is this quote for?</p>
                        <input
                            type="text"
                            value={uploadJobId}
                            onChange={(e) => setUploadJobId(e.target.value.toUpperCase())}
                            placeholder="e.g., COST-00123456"
                            className="w-full px-4 py-2 border border-gray-200 rounded-xl mb-4 focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 outline-none"
                        />
                        <div className="flex justify-end gap-2">
                            <button
                                onClick={() => { setShowUploadModal(false); setUploadFile(null); }}
                                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-xl transition-all"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    setShowUploadModal(false);
                                    if (uploadFile && uploadJobId) {
                                        handleUploadQuote(uploadFile, uploadJobId);
                                    }
                                }}
                                disabled={!uploadJobId}
                                className="px-4 py-2 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-700 disabled:opacity-50 transition-all"
                            >
                                Upload
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
