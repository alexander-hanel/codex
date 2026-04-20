//! External task feedback inbox watcher built on top of the generic [`FileWatcher`].

use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_protocol::ThreadId;
use codex_protocol::protocol::ExternalTaskFeedback;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;
use tokio::runtime::Handle;
use tokio::sync::broadcast;
use tracing::warn;

use crate::file_watcher::FileWatcher;
use crate::file_watcher::FileWatcherSubscriber;
use crate::file_watcher::Receiver;
use crate::file_watcher::ThrottledWatchReceiver;
use crate::file_watcher::WatchPath;
use crate::file_watcher::WatchRegistration;

#[cfg(not(test))]
const WATCHER_THROTTLE_INTERVAL: Duration = Duration::from_millis(500);
#[cfg(test)]
const WATCHER_THROTTLE_INTERVAL: Duration = Duration::from_millis(50);

const IPC_DIR: &str = "ipc";
const SESSIONS_DIR: &str = "sessions";
const EXTERNAL_TASK_FEEDBACK_DIR: &str = "external-task-feedback";
const INBOX_DIR: &str = "inbox";
const ENVELOPE_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ExternalTaskFeedbackInboxWatcherEvent {
    InboxChanged { paths: Vec<PathBuf> },
}

pub(crate) struct ExternalTaskFeedbackInboxWatcher {
    subscriber: FileWatcherSubscriber,
    tx: broadcast::Sender<ExternalTaskFeedbackInboxWatcherEvent>,
}

impl ExternalTaskFeedbackInboxWatcher {
    pub(crate) fn new(file_watcher: &Arc<FileWatcher>) -> Self {
        let (subscriber, rx) = file_watcher.add_subscriber();
        let (tx, _) = broadcast::channel(128);
        let watcher = Self {
            subscriber,
            tx: tx.clone(),
        };
        Self::spawn_event_loop(rx, tx);
        watcher
    }

    #[cfg(test)]
    pub(crate) fn noop() -> Self {
        Self::new(&Arc::new(FileWatcher::noop()))
    }

    pub(crate) fn subscribe(&self) -> broadcast::Receiver<ExternalTaskFeedbackInboxWatcherEvent> {
        self.tx.subscribe()
    }

    pub(crate) async fn register_inbox(
        &self,
        codex_home: &AbsolutePathBuf,
    ) -> std::io::Result<WatchRegistration> {
        let inbox_dir = external_task_feedback_inbox_dir(codex_home);
        tokio::fs::create_dir_all(&inbox_dir).await?;
        Ok(self.subscriber.register_paths(vec![WatchPath {
            path: inbox_dir,
            recursive: false,
        }]))
    }

    fn spawn_event_loop(
        rx: Receiver,
        tx: broadcast::Sender<ExternalTaskFeedbackInboxWatcherEvent>,
    ) {
        let mut rx = ThrottledWatchReceiver::new(rx, WATCHER_THROTTLE_INTERVAL);
        if let Ok(handle) = Handle::try_current() {
            handle.spawn(async move {
                while let Some(event) = rx.recv().await {
                    let _ = tx.send(ExternalTaskFeedbackInboxWatcherEvent::InboxChanged {
                        paths: event.paths,
                    });
                }
            });
        } else {
            warn!("external task feedback inbox watcher skipped: no Tokio runtime available");
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct ExternalTaskFeedbackInboxEnvelope {
    #[serde(default = "external_task_feedback_envelope_version")]
    pub(crate) version: u32,
    pub(crate) thread_id: ThreadId,
    pub(crate) feedback: ExternalTaskFeedback,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct ExternalTaskFeedbackSessionRegistration {
    pub(crate) thread_id: ThreadId,
    pub(crate) process_id: u32,
    pub(crate) cwd: PathBuf,
    pub(crate) inbox_path: PathBuf,
    pub(crate) created_at: i64,
}

const fn external_task_feedback_envelope_version() -> u32 {
    ENVELOPE_VERSION
}

pub(crate) fn external_task_feedback_inbox_dir(codex_home: &AbsolutePathBuf) -> PathBuf {
    codex_home
        .join(IPC_DIR)
        .join(EXTERNAL_TASK_FEEDBACK_DIR)
        .join(INBOX_DIR)
        .to_path_buf()
}

pub(crate) fn external_task_feedback_session_registry_path(
    codex_home: &AbsolutePathBuf,
    thread_id: ThreadId,
) -> PathBuf {
    codex_home
        .join(IPC_DIR)
        .join(SESSIONS_DIR)
        .join(format!("{thread_id}.json"))
        .to_path_buf()
}

pub(crate) fn external_task_feedback_targets_thread(path: &Path, thread_id: ThreadId) -> bool {
    let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    let prefix = format!("{thread_id}.");
    file_name.starts_with(&prefix) && file_name.ends_with(".json")
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use tokio::time::Duration;
    use tokio::time::timeout;

    #[test]
    fn target_file_filter_matches_expected_pattern() {
        let thread_id = ThreadId::default();
        assert!(external_task_feedback_targets_thread(
            Path::new(&format!("{thread_id}.blocked.json")),
            thread_id
        ));
        assert!(!external_task_feedback_targets_thread(
            Path::new("not-a-match.json"),
            thread_id
        ));
        assert!(!external_task_feedback_targets_thread(
            Path::new(&format!("{thread_id}.blocked.tmp")),
            thread_id
        ));
    }

    #[tokio::test]
    async fn forwards_file_watcher_events() {
        let file_watcher = Arc::new(FileWatcher::noop());
        let watcher = ExternalTaskFeedbackInboxWatcher::new(&file_watcher);
        let mut rx = watcher.subscribe();
        let _registration = watcher
            .subscriber
            .register_path(PathBuf::from("feedback-inbox"), /*recursive*/ false);

        file_watcher
            .send_paths_for_test(vec![PathBuf::from("feedback-inbox/blocked.json")])
            .await;

        let event = timeout(Duration::from_secs(2), rx.recv())
            .await
            .expect("feedback inbox watcher event")
            .expect("broadcast recv");
        assert_eq!(
            event,
            ExternalTaskFeedbackInboxWatcherEvent::InboxChanged {
                paths: vec![PathBuf::from("feedback-inbox/blocked.json")],
            }
        );
    }
}
