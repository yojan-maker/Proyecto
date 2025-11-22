# train_classifier.py
import os
import argparse
import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.callbacks import ModelCheckpoint, ReduceLROnPlateau, EarlyStopping

def build_model(num_classes, input_shape=(224,224,3)):
    base = MobileNetV2(weights='imagenet', include_top=False, input_shape=input_shape)
    base.trainable = False
    x = layers.GlobalAveragePooling2D()(base.output)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(256, activation='relu')(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(num_classes, activation='softmax')(x)
    model = models.Model(inputs=base.input, outputs=outputs)
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
    return model

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', default='dataset_split', help='dataset split dir with train/val/test')
    parser.add_argument('--img_size', type=int, default=224)
    parser.add_argument('--batch', type=int, default=32)
    parser.add_argument('--epochs', type=int, default=15)
    parser.add_argument('--out', default='model.h5')
    args = parser.parse_args()

    train_dir = os.path.join(args.data_dir, 'train')
    val_dir = os.path.join(args.data_dir, 'val')

    train_gen = ImageDataGenerator(rescale=1./255,
                                   rotation_range=15,
                                   width_shift_range=0.1,
                                   height_shift_range=0.1,
                                   shear_range=0.1,
                                   zoom_range=0.1,
                                   horizontal_flip=True,
                                   fill_mode='nearest')
    val_gen = ImageDataGenerator(rescale=1./255)

    train_flow = train_gen.flow_from_directory(train_dir, target_size=(args.img_size, args.img_size),
                                               batch_size=args.batch, class_mode='categorical')
    val_flow = val_gen.flow_from_directory(val_dir, target_size=(args.img_size, args.img_size),
                                           batch_size=args.batch, class_mode='categorical')

    num_classes = len(train_flow.class_indices)
    model = build_model(num_classes, input_shape=(args.img_size, args.img_size, 3))
    print("Classes:", train_flow.class_indices)

    callbacks = [
        ModelCheckpoint(args.out, save_best_only=True, monitor='val_accuracy', mode='max'),
        ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=3),
        EarlyStopping(monitor='val_loss', patience=6, restore_best_weights=True)
    ]

    history = model.fit(train_flow, validation_data=val_flow, epochs=args.epochs, callbacks=callbacks)
    model.save(args.out)
    print("Model saved to", args.out)

if __name__ == '__main__':
    main()
