#include <QGuiApplication>
#include <QDateTime>
#include <QDebug>
#include <QEvent>
#include <QWindow>

class ProbeWindow final : public QWindow {
public:
    explicit ProbeWindow(const QString &name) : name_(name) {
        setTitle(name);
        resize(400, 300);
    }

    bool event(QEvent *e) override {
        const char *kind = nullptr;
        switch (e->type()) {
        case QEvent::WindowActivate: kind = "focus_in"; break;
        case QEvent::WindowDeactivate: kind = "focus_out"; break;
        case QEvent::Resize: kind = "resize"; break;
        case QEvent::Close: kind = "close"; break;
        case QEvent::Expose: kind = "expose"; break;
        default: break;
        }
        if (kind) {
            qInfo().noquote() << QString("{\"client\":\"%1\",\"event\":\"%2\",\"time_ms\":%3,\"width\":%4,\"height\":%5}")
                .arg(name_, kind).arg(QDateTime::currentMSecsSinceEpoch()).arg(width()).arg(height());
        }
        return QWindow::event(e);
    }

private:
    QString name_;
};

int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    if (argc != 2) return 2;
    ProbeWindow window(QString::fromLocal8Bit(argv[1]));
    window.show();
    return app.exec();
}
