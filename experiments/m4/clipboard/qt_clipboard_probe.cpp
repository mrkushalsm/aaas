#include <QApplication>
#include <QClipboard>
#include <QCryptographicHash>
#include <QDeadlineTimer>
#include <QFile>
#include <QLineEdit>
#include <QTimer>

#include <cstdio>

static QByteArray digest(const QString &value) {
    return QCryptographicHash::hash(value.toUtf8(), QCryptographicHash::Sha256).toHex();
}

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    if (argc < 3) return 2;
    QWidget window;
    window.setWindowTitle(QStringLiteral("AaaS Clipboard Probe"));
    auto *field = new QLineEdit(&window);
    window.resize(620, 100);
    window.show();
    field->setFocus();
    QClipboard *clipboard = QApplication::clipboard();
    const QByteArray mode(argv[1]);
    if (mode == "--paste-sha256") {
        if (argc < 4) return 2;
        const QByteArray expected(argv[2]);
        const QString result_path = QString::fromLocal8Bit(argv[3]);
        QTimer timer;
        timer.setInterval(30);
        const auto deadline = QDeadlineTimer(15000);
        QObject::connect(&timer, &QTimer::timeout, &app, [&]() {
            if (deadline.hasExpired()) {
                QFile result(result_path);
                if (result.open(QIODevice::WriteOnly)) result.write("TIMEOUT\n");
                app.quit();
                return;
            }
            if (digest(clipboard->text(QClipboard::Clipboard)) != expected) return;
            field->setFocus();
            field->paste();
            QTimer::singleShot(150, &app, [&]() {
                const QByteArray actual = digest(field->text());
                QFile result(result_path);
                if (result.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                    result.write(actual);
                    result.write("\n");
                    result.write(actual == expected ? "PASS\n" : "MISMATCH\n");
                }
                std::printf("PASTE sha256=%s result=%s\n", actual.constData(),
                            actual == expected ? "PASS" : "MISMATCH");
                app.quit();
            });
            timer.stop();
        });
        timer.start();
        return app.exec();
    }
    if (mode == "--set") {
        const QString value = QString::fromUtf8(argv[2]);
        const QByteArray expected = digest(value);
        const QString result_path = argc > 3 ? QString::fromLocal8Bit(argv[3]) : QString();
        QTimer::singleShot(1500, &app, [&]() {
            field->setFocus();
            clipboard->setText(value, QClipboard::Clipboard);
            QTimer::singleShot(250, &app, [&]() {
                const QByteArray actual = digest(clipboard->text(QClipboard::Clipboard));
                if (!result_path.isEmpty()) {
                    QFile result(result_path);
                    if (result.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                        result.write(actual);
                        result.write("\n");
                        result.write(actual == expected ? "PASS\n" : "MISMATCH\n");
                    }
                }
                std::printf("SET sha256=%s result=%s\n", actual.constData(),
                            actual == expected ? "PASS" : "MISMATCH");
                app.quit();
            });
        });
        return app.exec();
    }
    if (mode == "--wait-copy") {
        const QString value = QString::fromUtf8(argv[2]);
        const QByteArray expected = digest(value);
        const QString result_path = argc > 3 ? QString::fromLocal8Bit(argv[3]) : QString();
        field->setText(value);
        field->selectAll();
        QTimer timer;
        timer.setInterval(30);
        const auto deadline = QDeadlineTimer(12000);
        QObject::connect(&timer, &QTimer::timeout, &app, [&]() {
            const QByteArray actual = digest(clipboard->text(QClipboard::Clipboard));
            if (actual == expected || deadline.hasExpired()) {
                const bool passed = actual == expected;
                if (!result_path.isEmpty()) {
                    QFile result(result_path);
                    if (result.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                        result.write(actual);
                        result.write("\n");
                        result.write(passed ? "PASS\n" : "TIMEOUT\n");
                    }
                }
                std::printf("COPY sha256=%s result=%s\n", actual.constData(),
                            passed ? "PASS" : "TIMEOUT");
                app.quit();
            }
        });
        timer.start();
        return app.exec();
    }
    return 2;
}
