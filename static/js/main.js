document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const videoFileEl = document.getElementById('videoFile');
    const uploadBox = document.getElementById('upload-box');
    const uploadBtn = uploadBox.querySelector('.upload-btn');
    
    const originalVideoDisplay = document.getElementById('original-video-display');
    const trimmedVideoDisplay = document.getElementById('trimmed-video-display');
    
    const timelineContainer = document.getElementById('timeline-container');
    const timelineRuler = document.getElementById('timeline-ruler');
    const timelinePlayhead = document.getElementById('timeline-playhead');
    const timelineSegments = document.getElementById('timeline-segments');
    const currentTimeEl = document.getElementById('current-time');
    const totalDurationEl = document.getElementById('total-duration');
    
    const queryForm = document.getElementById('queryForm');
    const queryInput = document.getElementById('query');
    const submitQueryBtn = document.getElementById('submit-query-btn');
    
    const statusContainer = document.getElementById('analysis-status-container');
    const analysisLog = document.getElementById('analysis-log');

    // Chat elements
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const chatMessages = document.getElementById('chat-messages');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const sendChatBtn = document.getElementById('send-chat-btn');

    // --- State ---
    let originalVideoPlayer = null;
    let videoDuration = 0;
    let currentVideoFile = null;

    // Store the current temp video path for cleanup
    window.currentTempVideoPath = null;

    // --- UTILITY FUNCTIONS ---
    const formatTime = (seconds) => {
        if (isNaN(seconds) || seconds < 0) {
            return "00:00.0";
        }
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        const ms = Math.floor((seconds - (mins * 60 + secs)) * 10);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms}`;
    };
    
    const setStatus = (message, type = 'info') => {
        statusContainer.innerHTML = `<p class="${type}">${message}</p>`;
    };

    // Tab switching functionality
    const rightColumn = document.querySelector('.right-column');
    const switchTab = (tabName) => {
        tabButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });
        tabContents.forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}-tab`);
        });
        // Expand chat and hide trimmed video when in chat tab
        if (tabName === 'chat') {
            rightColumn.classList.add('chat-full');
        } else {
            rightColumn.classList.remove('chat-full');
        }
    };

    // Chat functionality
    const addChatMessage = (message, sender) => {
        const messageEl = document.createElement('div');
        messageEl.classList.add('chat-message', sender);
        
        const avatar = document.createElement('div');
        avatar.classList.add('message-avatar', sender);
        avatar.textContent = sender === 'user' ? 'U' : 'V';
        
        const content = document.createElement('div');
        content.classList.add('message-content');
        content.textContent = message;
        
        messageEl.appendChild(avatar);
        messageEl.appendChild(content);
        
        chatMessages.appendChild(messageEl);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    const addLoadingMessage = () => {
        const loadingEl = document.createElement('div');
        loadingEl.classList.add('chat-message', 'video');
        loadingEl.id = 'loading-message';
        
        const avatar = document.createElement('div');
        avatar.classList.add('message-avatar', 'video');
        avatar.textContent = 'V';
        
        const content = document.createElement('div');
        content.classList.add('chat-loading');
        content.innerHTML = '<div class="spinner"></div><span>Video is thinking...</span>';
        
        loadingEl.appendChild(avatar);
        loadingEl.appendChild(content);
        
        chatMessages.appendChild(loadingEl);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    const removeLoadingMessage = () => {
        const loadingEl = document.getElementById('loading-message');
        if (loadingEl) {
            loadingEl.remove();
        }
    };

    const sendChatMessage = async (message) => {
        if (!currentVideoFile) {
            addChatMessage('Please upload a video first to start chatting!', 'video');
            return;
        }

        addChatMessage(message, 'user');
        addLoadingMessage();
        
        try {
            const formData = new FormData();
            formData.append('video', currentVideoFile);
            formData.append('message', message);

            const response = await fetch('/api/chat', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            removeLoadingMessage();

            if (response.ok) {
                addChatMessage(result.response, 'video');
            } else {
                addChatMessage(`Sorry, I encountered an error: ${result.error}`, 'video');
            }
        } catch (error) {
            removeLoadingMessage();
            addChatMessage('Sorry, I encountered a network error. Please try again.', 'video');
            console.error('Chat error:', error);
        }
    };

    const createVideoPlayer = (src, isOriginalPlayer) => {
        const player = document.createElement('video');
        player.src = src;
        player.controls = true;

        if (isOriginalPlayer) {
            player.addEventListener('loadedmetadata', () => {
                videoDuration = player.duration;
                totalDurationEl.textContent = formatTime(videoDuration);
                timelineContainer.classList.remove('hidden');
            });
            player.addEventListener('timeupdate', () => {
                const percentage = videoDuration ? (player.currentTime / videoDuration) * 100 : 0;
                timelinePlayhead.style.left = `${percentage}%`;
                currentTimeEl.textContent = formatTime(player.currentTime);
            });
        }
        return player;
    };
    
    const addTimelineMarker = ({ startTime, endTime }) => {
        if (!videoDuration) return;
        const marker = document.createElement('div');
        marker.classList.add('timeline-segment-marker');
        marker.style.left = `${(startTime / videoDuration) * 100}%`;
        marker.style.width = `${((endTime - startTime) / videoDuration) * 100}%`;
        timelineSegments.appendChild(marker);
        
        marker.addEventListener('click', () => {
            if (originalVideoPlayer) {
                originalVideoPlayer.currentTime = startTime;
            }
        });
    };

    // --- EVENT HANDLERS ---
    const handleFileUpload = (file) => {
        if (!file) return;

        const videoUrl = URL.createObjectURL(file);
        originalVideoPlayer = createVideoPlayer(videoUrl, true);
        
        originalVideoDisplay.innerHTML = '';
        originalVideoDisplay.appendChild(originalVideoPlayer);
        
        // Enable both analysis and chat
        queryInput.disabled = false;
        submitQueryBtn.disabled = false;
        chatInput.disabled = false;
        sendChatBtn.disabled = false;
        
        // Store video file for chat
        currentVideoFile = file;
        
        setStatus('Video loaded. Ready for analysis and chat.');
        analysisLog.innerHTML = '';
        trimmedVideoDisplay.innerHTML = '<div class="placeholder"><i class="fas fa-search"></i><p>Awaiting analysis...</p></div>';
        
        // Clear chat and add welcome message
        chatMessages.innerHTML = `
            <div class="chat-welcome">
                <i class="fas fa-comments"></i>
                <p>Video loaded! You can now chat with your video. Ask questions, get descriptions, or just have a conversation!</p>
            </div>
        `;
    };

    // Tab switching
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            switchTab(btn.dataset.tab);
        });
    });

    // Chat form submission
    chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;

        chatInput.value = '';
        await sendChatMessage(message);
    });

    // Enter key handling for chat
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    uploadBtn.addEventListener('click', () => videoFileEl.click());
    videoFileEl.addEventListener('change', (e) => handleFileUpload(e.target.files[0]));
    ['dragover', 'drop'].forEach(eventName => {
        originalVideoDisplay.addEventListener(eventName, e => e.preventDefault());
    });
    originalVideoDisplay.addEventListener('drop', e => handleFileUpload(e.dataTransfer.files[0]));

    queryForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData();
        formData.append('video', videoFileEl.files[0]);
        formData.append('query', queryInput.value);

        submitQueryBtn.disabled = true;
        submitQueryBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Analyzing...';
        setStatus('Step 1/3: Uploading and analyzing video...');

        try {
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });
            const uploadResult = await response.json();
            // Store the temp video path for cleanup
            window.currentTempVideoPath = uploadResult.video_path;

            // Now call process-video
            const processResponse = await fetch('/api/process-video', {
                method: 'POST',
                body: formData
            });

            setStatus('Step 2/3: Processing AI response...');
            const result = await processResponse.json();

            if (processResponse.ok && result.found) {
                setStatus('Step 3/3: Analysis complete! Segment found.');
                const trimmedVideoPlayer = createVideoPlayer(result.download_url, false);
                trimmedVideoDisplay.innerHTML = '';
                trimmedVideoDisplay.appendChild(trimmedVideoPlayer);
                trimmedVideoPlayer.play();

                addTimelineMarker(result);
                
                const logItem = document.createElement('div');
                logItem.classList.add('log-item');
                logItem.innerHTML = `
                    <p><strong>Query:</strong> "${queryInput.value}"</p>
                    <p><strong>Found:</strong> <span class="log-timestamp">${formatTime(result.start_time)} - ${formatTime(result.end_time)}</span></p>
                `;
                analysisLog.prepend(logItem);
                
                queryInput.value = '';
            } else {
                setStatus(`Analysis failed: ${result.error || result.message}`, 'error');
                trimmedVideoDisplay.innerHTML = '<div class="placeholder"><i class="fas fa-exclamation-triangle"></i><p>Could not find segment.</p></div>';
            }
        } catch (error) {
            setStatus(`An unexpected error occurred: ${error.message}`, 'error');
            console.error('Submission error:', error);
        } finally {
            submitQueryBtn.disabled = false;
            submitQueryBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Analyze';
        }
    });

    timelineRuler.addEventListener('click', (e) => {
        if (!originalVideoPlayer || !videoDuration) return;
        const timelineRect = timelineRuler.getBoundingClientRect();
        const clickX = e.clientX - timelineRect.left;
        const clickPercent = clickX / timelineRect.width;
        originalVideoPlayer.currentTime = videoDuration * clickPercent;
    });

    // Cleanup temp file on tab close
    window.addEventListener('beforeunload', function () {
        if (window.currentTempVideoPath) {
            const data = JSON.stringify({ temp_video_path: window.currentTempVideoPath });
            navigator.sendBeacon('/api/cleanup-temp', data);
        }
    });
});
